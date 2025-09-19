"""
Natural Language Processing Service
שירות עיבוד שפה טבעית

This module provides NLP capabilities for the Animal Rescue Bot, including:
- Text analysis and keyword extraction
- Urgency level detection
- Animal type classification
- Sentiment analysis
- Language detection
- Text similarity and duplicate detection
"""

import asyncio
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass

import structlog
from app.core.config import settings
from app.models.database import AnimalType, UrgencyLevel
from app.core.cache import cache, cached

# =============================================================================
# Logger Setup
# =============================================================================

logger = structlog.get_logger(__name__)

# =============================================================================
# NLP Data Structures
# =============================================================================

@dataclass
class NLPResult:
    """Result of NLP analysis."""
    urgency_level: UrgencyLevel
    animal_type: AnimalType
    keywords: List[str]
    sentiment: float
    confidence: float
    language: str
    extracted_entities: Dict[str, List[str]]


@dataclass
class SimilarityResult:
    """Result of text similarity analysis."""
    similarity_score: float
    matching_keywords: List[str]
    is_duplicate: bool
    confidence: float


# =============================================================================
# Language Detection and Processing
# =============================================================================

class LanguageDetector:
    """Language detection for Hebrew, Arabic, and English text."""
    
    # Character ranges for different languages
    HEBREW_CHARS = set(range(0x0590, 0x05FF + 1))
    ARABIC_CHARS = set(range(0x0600, 0x06FF + 1)) | set(range(0xFE70, 0xFEFF + 1))
    
    # Common words in each language
    HEBREW_COMMON = {
        'של', 'את', 'על', 'עם', 'לא', 'זה', 'היה', 'הוא', 'היא', 'אני', 'אתה', 
        'אתם', 'הם', 'הן', 'מה', 'איך', 'איפה', 'מתי', 'למה', 'כן', 'רק', 'גם',
        'כל', 'יש', 'אין', 'צריך', 'רוצה', 'יכול', 'חיה', 'בעל', 'חיים', 'כלב',
        'חתול', 'פצוע', 'עזרה', 'דחוף', 'מיד', 'בבקשה', 'תודה', 'שלום'
    }
    
    ARABIC_COMMON = {
        'في', 'من', 'إلى', 'على', 'هذا', 'هذه', 'ذلك', 'التي', 'الذي', 'كان', 
        'كانت', 'يكون', 'تكون', 'هو', 'هي', 'أنا', 'أنت', 'نحن', 'هم', 'هن',
        'ما', 'كيف', 'أين', 'متى', 'لماذا', 'نعم', 'لا', 'فقط', 'أيضا', 'كل',
        'يوجد', 'لا يوجد', 'يجب', 'يريد', 'يمكن', 'حيوان', 'كلب', 'قطة', 'مصاب',
        'مساعدة', 'عاجل', 'فورا', 'من فضلك', 'شكرا', 'مرحبا'
    }
    
    ENGLISH_COMMON = {
        'the', 'of', 'and', 'a', 'to', 'in', 'is', 'you', 'that', 'it', 'he', 
        'was', 'for', 'on', 'are', 'as', 'with', 'his', 'they', 'i', 'at', 'be',
        'this', 'have', 'from', 'or', 'one', 'had', 'by', 'word', 'but', 'not',
        'what', 'all', 'were', 'we', 'when', 'your', 'can', 'said', 'there',
        'animal', 'dog', 'cat', 'pet', 'injured', 'help', 'urgent', 'emergency',
        'please', 'thank', 'hello', 'found', 'lost', 'rescue'
    }
    
    def detect_language(self, text: str) -> Tuple[str, float]:
        """
        Detect language of text.
        
        Args:
            text: Text to analyze
            
        Returns:
            Tuple of (language_code, confidence)
        """
        if not text.strip():
            return "he", 0.0  # Default to Hebrew
        
        # Character-based detection
        hebrew_chars = sum(1 for char in text if ord(char) in self.HEBREW_CHARS)
        arabic_chars = sum(1 for char in text if ord(char) in self.ARABIC_CHARS)
        total_chars = len([char for char in text if char.isalpha()])
        
        if total_chars == 0:
            return "he", 0.0
        
        hebrew_ratio = hebrew_chars / total_chars
        arabic_ratio = arabic_chars / total_chars
        
        # If clear script detection
        if hebrew_ratio > 0.3:
            return "he", min(1.0, hebrew_ratio + 0.2)
        elif arabic_ratio > 0.3:
            return "ar", min(1.0, arabic_ratio + 0.2)
        
        # Word-based detection for Latin script
        words = set(re.findall(r'\b\w+\b', text.lower()))
        
        hebrew_score = len(words & self.HEBREW_COMMON) / max(len(words), 1)
        arabic_score = len(words & self.ARABIC_COMMON) / max(len(words), 1)
        english_score = len(words & self.ENGLISH_COMMON) / max(len(words), 1)
        
        # Combine scores
        scores = {
            "he": hebrew_ratio + hebrew_score,
            "ar": arabic_ratio + arabic_score,
            "en": english_score
        }
        
        detected_lang = max(scores.keys(), key=lambda k: scores[k])
        confidence = scores[detected_lang]
        
        # Default to Hebrew if confidence is very low
        if confidence < 0.1:
            return "he", 0.1
        
        return detected_lang, min(1.0, confidence)


# =============================================================================
# Keyword Extraction and Text Analysis
# =============================================================================

class KeywordExtractor:
    """Extract relevant keywords from animal rescue reports."""
    
    def __init__(self):
        # Keywords by category and language
        self.keywords = {
            # Animal types
            "animals": {
                "he": {
                    "dog": ["כלב", "כלבה", "גור", "כלבים", "כלבות", "גורים"],
                    "cat": ["חתול", "חתולה", "גור", "חתולים", "חתולות", "גורים", "חתלתול"],
                    "bird": ["ציפור", "עוף", "ציפורים", "עופות", "תוכי", "יונה", "עורב"],
                    "wildlife": ["חיות בר", "שועל", "חזיר בר", "נחש", "לטאה", "צב", "ארנב"],
                    "livestock": ["פרה", "סוס", "עז", "כבש", "חמור", "בקר"],
                    "exotic": ["זוחל", "נחש", "לטאה", "אקזוטי", "נדיר"]
                },
                "ar": {
                    "dog": ["كلب", "كلاب", "جرو", "كليب"],
                    "cat": ["قطة", "قط", "قطط", "هرة", "قطيط"],
                    "bird": ["طائر", "طيور", "عصفور", "حمامة", "غراب"],
                    "wildlife": ["حيوانات برية", "ثعلب", "خنزير بري", "ثعبان", "سحلية", "سلحفاة", "أرنب"],
                    "livestock": ["بقرة", "حصان", "ماعز", "خروف", "حمار"],
                    "exotic": ["زاحف", "ثعبان", "سحلية", "غريب", "نادر"]
                },
                "en": {
                    "dog": ["dog", "puppy", "canine", "pup", "doggy", "mutt", "hound"],
                    "cat": ["cat", "kitten", "feline", "kitty", "tom", "tabby"],
                    "bird": ["bird", "chick", "avian", "pigeon", "crow", "parrot", "dove"],
                    "wildlife": ["wild", "fox", "boar", "snake", "lizard", "turtle", "rabbit", "wildlife"],
                    "livestock": ["cow", "horse", "goat", "sheep", "donkey", "cattle", "livestock"],
                    "exotic": ["reptile", "snake", "lizard", "exotic", "rare", "unusual"]
                }
            },
            
            # Urgency indicators
            "urgency": {
                "he": {
                    "critical": ["מת", "גוסס", "דם", "דימום", "לא נושם", "מחוסר הכרה", "קריטי", "מיידי"],
                    "high": ["פצוע קשה", "כאב", "צולע", "חירום", "דחוף", "מהר", "בטוח"],
                    "medium": ["פצוע", "עזרה", "תקוע", "אבוד", "נטוש", "רעב"],
                    "low": ["נמצא", "מחפש", "בעלים", "חסר", "בריא", "רגיל"]
                },
                "ar": {
                    "critical": ["ميت", "يموت", "دم", "نزيف", "لا يتنفس", "فاقد الوعي", "حرج", "فوري"],
                    "high": ["مصاب بشدة", "ألم", "يعرج", "طوارئ", "عاجل", "بسرعة", "آمن"],
                    "medium": ["مصاب", "مساعدة", "عالق", "ضائع", "مهجور", "جائع"],
                    "low": ["موجود", "يبحث", "مالك", "مفقود", "صحي", "عادي"]
                },
                "en": {
                    "critical": ["dead", "dying", "blood", "bleeding", "not breathing", "unconscious", "critical", "immediate"],
                    "high": ["severely injured", "pain", "limping", "emergency", "urgent", "quickly", "safe"],
                    "medium": ["injured", "help", "stuck", "lost", "abandoned", "hungry"],
                    "low": ["found", "looking", "owner", "missing", "healthy", "normal"]
                }
            },
            
            # Location indicators
            "location": {
                "he": {
                    "road": ["כביש", "דרך", "רחוב", "צומת", "מדרכה", "כביש ראשי"],
                    "park": ["פארק", "גינה", "גן", "יער", "שמורה", "טבע"],
                    "building": ["בניין", "בית", "חנות", "מרכז", "בית ספר", "בית חולים"],
                    "water": ["חוף", "ים", "נהר", "נחל", "בריכה", "מים"]
                },
                "ar": {
                    "road": ["شارع", "طريق", "ممر", "تقاطع", "رصيف", "طريق رئيسي"],
                    "park": ["حديقة", "متنزه", "غابة", "محمية", "طبيعة"],
                    "building": ["مبنى", "بيت", "محل", "مركز", "مدرسة", "مستشفى"],
                    "water": ["شاطئ", "بحر", "نهر", "جدول", "بركة", "مياه"]
                },
                "en": {
                    "road": ["street", "road", "highway", "intersection", "sidewalk", "main road"],
                    "park": ["park", "garden", "forest", "reserve", "nature", "woods"],
                    "building": ["building", "house", "shop", "center", "school", "hospital"],
                    "water": ["beach", "sea", "river", "stream", "pond", "water"]
                }
            }
        }
    
    def extract_keywords(self, text: str, language: str = "he") -> Dict[str, List[str]]:
        """
        Extract keywords from text by category.
        
        Args:
            text: Text to analyze
            language: Language code (he/ar/en)
            
        Returns:
            Dictionary of keyword categories and found keywords
        """
        text_lower = text.lower()
        results = {
            "animals": [],
            "urgency": [],
            "location": [],
            "general": []
        }
        
        # Extract keywords by category
        for category, lang_data in self.keywords.items():
            if language in lang_data:
                for subcategory, keywords in lang_data[language].items():
                    found_keywords = [kw for kw in keywords if kw.lower() in text_lower]
                    if found_keywords:
                        results[category].extend(found_keywords)
        
        # Extract general keywords (nouns and adjectives)
        general_keywords = self._extract_general_keywords(text, language)
        results["general"] = general_keywords
        
        # Remove duplicates and empty categories
        for category in results:
            results[category] = list(set(results[category]))
        
        return results
    
    def _extract_general_keywords(self, text: str, language: str) -> List[str]:
        """Extract general keywords from text."""
        # Simple word extraction with filtering
        words = re.findall(r'\b\w+\b', text.lower())
        
        # Filter common stop words and short words
        stop_words = {
            "he": {"של", "את", "על", "עם", "לא", "זה", "היה", "הוא", "היא", "אני", "אתה", "או", "אם", "כי", "גם", "רק"},
            "ar": {"في", "من", "إلى", "على", "هذا", "هذه", "ذلك", "التي", "الذي", "كان", "كانت", "أو", "إذا", "لأن", "أيضا", "فقط"},
            "en": {"the", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by", "if", "then", "also", "only"}
        }.get(language, set())
        
        filtered_words = [
            word for word in words 
            if len(word) > 2 and word not in stop_words and not word.isdigit()
        ]
        
        # Return most common words
        word_counts = Counter(filtered_words)
        return [word for word, count in word_counts.most_common(10)]


# =============================================================================
# Urgency Level Detection
# =============================================================================

class UrgencyDetector:
    """Detect urgency level from text descriptions."""
    
    def __init__(self):
        self.urgency_patterns = {
            "critical": {
                "he": [
                    r'מת|גוסס|לא נושם|דם|דימום|מחוסר הכרה',
                    r'קריטי|מיידי|חירום קיצוני',
                    r'עכשיו מיד|בלי דיחוי|חירום'
                ],
                "ar": [
                    r'ميت|يموت|لا يتنفس|دم|نزيف|فاقد الوعي',
                    r'حرج|فوري|طوارئ قصوى',
                    r'الآن فورا|بدون تأخير|طوارئ'
                ],
                "en": [
                    r'dead|dying|not breathing|blood|bleeding|unconscious',
                    r'critical|immediate|extreme emergency',
                    r'right now|no delay|emergency'
                ]
            },
            "high": {
                "he": [
                    r'פצוע קשה|כאב חזק|צולע|לא יכול לזוז',
                    r'דחוף|חירום|מהר|כואב',
                    r'נראה רע|במצב קשה'
                ],
                "ar": [
                    r'مصاب بشدة|ألم شديد|يعرج|لا يستطيع الحركة',
                    r'عاجل|طوارئ|بسرعة|يؤلم',
                    r'يبدو سيئا|في حالة سيئة'
                ],
                "en": [
                    r'severely injured|intense pain|limping|cannot move',
                    r'urgent|emergency|quickly|hurts',
                    r'looks bad|in poor condition'
                ]
            },
            "medium": {
                "he": [
                    r'פצוע|עזרה|תקוע|אבוד|נטוש',
                    r'רעב|צמא|קר|חם',
                    r'מפחד|לבד|צריך עזרה'
                ],
                "ar": [
                    r'مصاب|مساعدة|عالق|ضائع|مهجور',
                    r'جائع|عطشان|بارد|حار',
                    r'خائف|وحيد|يحتاج مساعدة'
                ],
                "en": [
                    r'injured|help|stuck|lost|abandoned',
                    r'hungry|thirsty|cold|hot',
                    r'scared|alone|needs help'
                ]
            },
            "low": {
                "he": [
                    r'נמצא|מחפש בעלים|בריא|רגיל',
                    r'נראה בסדר|לא בדחיפות',
                    r'יכול לחכות|לא קריטי'
                ],
                "ar": [
                    r'موجود|يبحث عن مالك|صحي|عادي',
                    r'يبدو بخير|ليس عاجلا',
                    r'يمكنه الانتظار|غير حرج'
                ],
                "en": [
                    r'found|looking for owner|healthy|normal',
                    r'seems okay|not urgent',
                    r'can wait|not critical'
                ]
            }
        }
    
    def detect_urgency(self, text: str, language: str = "he") -> Tuple[UrgencyLevel, float]:
        """
        Detect urgency level from text.
        
        Args:
            text: Text to analyze
            language: Language code
            
        Returns:
            Tuple of (urgency_level, confidence)
        """
        text_lower = text.lower()
        scores = {level: 0 for level in ["critical", "high", "medium", "low"]}
        
        # Check patterns for each urgency level
        for level, lang_patterns in self.urgency_patterns.items():
            if language in lang_patterns:
                for pattern in lang_patterns[language]:
                    matches = len(re.findall(pattern, text_lower))
                    scores[level] += matches
        
        # Convert scores to urgency levels
        if scores["critical"] > 0:
            return UrgencyLevel.CRITICAL, min(1.0, scores["critical"] * 0.8)
        elif scores["high"] > 0:
            return UrgencyLevel.HIGH, min(1.0, scores["high"] * 0.7)
        elif scores["medium"] > 0:
            return UrgencyLevel.MEDIUM, min(1.0, scores["medium"] * 0.6)
        elif scores["low"] > 0:
            return UrgencyLevel.LOW, min(1.0, scores["low"] * 0.5)
        else:
            # Default to medium if no clear indicators
            return UrgencyLevel.MEDIUM, 0.3


# =============================================================================
# Animal Type Classification
# =============================================================================

class AnimalClassifier:
    """Classify animal type from text descriptions."""
    
    def __init__(self):
        self.animal_patterns = {
            AnimalType.DOG: {
                "he": [r'כלב|כלבה|גור|כלבים|כלבות|גורים|רועה|רטריבר|פודל'],
                "ar": [r'كلب|كلاب|جرو|كليب'],
                "en": [r'dog|puppy|canine|pup|doggy|mutt|hound|retriever|shepherd|terrier']
            },
            AnimalType.CAT: {
                "he": [r'חתול|חתולה|גור|חתולים|חתולות|גורים|חתלתול|מיאו'],
                "ar": [r'قطة|قط|قطط|هرة|قطيط'],
                "en": [r'cat|kitten|feline|kitty|tom|tabby|meow']
            },
            AnimalType.BIRD: {
                "he": [r'ציפור|עוף|ציפורים|עופות|תוכי|יונה|עורב|דרור|פרפור|נשר'],
                "ar": [r'طائر|طيور|عصفور|حمامة|غراب|نسر'],
                "en": [r'bird|chick|avian|pigeon|crow|parrot|dove|eagle|sparrow|owl']
            },
            AnimalType.WILDLIFE: {
                "he": [r'חיות בר|שועל|חזיר בר|נחש|לטאה|צב|ארנב|עכבר|חולדה'],
                "ar": [r'حيوانات برية|ثعلب|خنزير بري|ثعبان|سحلية|سلحفاة|أرنب'],
                "en": [r'wild|fox|boar|snake|lizard|turtle|rabbit|wildlife|squirrel|hedgehog']
            },
            AnimalType.LIVESTOCK: {
                "he": [r'פרה|סוס|עז|כבש|חמור|בקר|סוסה|עגל|טלה|גדי'],
                "ar": [r'بقرة|حصان|ماعز|خروف|حمار|عجل|طلي'],
                "en": [r'cow|horse|goat|sheep|donkey|cattle|livestock|calf|lamb|foal']
            },
            AnimalType.EXOTIC: {
                "he": [r'זוחל|נחש|לטאה|אקזוטי|נדיר|משונה|לא רגיל|טרופי'],
                "ar": [r'زاحف|ثعبان|سحلية|غريب|نادر|غير عادي|استوائي'],
                "en": [r'reptile|snake|lizard|exotic|rare|unusual|tropical|iguana|gecko']
            }
        }
    
    def classify_animal(self, text: str, language: str = "he") -> Tuple[AnimalType, float]:
        """
        Classify animal type from text.
        
        Args:
            text: Text to analyze
            language: Language code
            
        Returns:
            Tuple of (animal_type, confidence)
        """
        text_lower = text.lower()
        scores = {}
        
        # Check patterns for each animal type
        for animal_type, lang_patterns in self.animal_patterns.items():
            if language in lang_patterns:
                score = 0
                for pattern in lang_patterns[language]:
                    matches = len(re.findall(pattern, text_lower))
                    score += matches
                
                if score > 0:
                    scores[animal_type] = score
        
        if not scores:
            return AnimalType.UNKNOWN, 0.0
        
        # Return animal type with highest score
        best_animal = max(scores.keys(), key=lambda k: scores[k])
        max_score = scores[best_animal]
        confidence = min(1.0, max_score * 0.6)
        
        return best_animal, confidence


# =============================================================================
# Sentiment Analysis
# =============================================================================

class SentimentAnalyzer:
    """Simple sentiment analysis for animal rescue texts."""
    
    def __init__(self):
        self.sentiment_words = {
            "positive": {
                "he": ["טוב", "בסדר", "בריא", "שמח", "יפה", "חזק", "בטוח", "הציל", "עזר"],
                "ar": ["جيد", "بخير", "صحي", "سعيد", "جميل", "قوي", "آمن", "أنقذ", "ساعد"],
                "en": ["good", "okay", "healthy", "happy", "beautiful", "strong", "safe", "saved", "helped"]
            },
            "negative": {
                "he": ["רע", "פצוע", "כואב", "חולה", "מפחד", "לבד", "רעב", "קר", "מת"],
                "ar": ["سيء", "مصاب", "يؤلم", "مريض", "خائف", "وحيد", "جائع", "بارد", "ميت"],
                "en": ["bad", "injured", "hurt", "sick", "scared", "alone", "hungry", "cold", "dead"]
            }
        }
    
    def analyze_sentiment(self, text: str, language: str = "he") -> float:
        """
        Analyze sentiment of text.
        
        Args:
            text: Text to analyze
            language: Language code
            
        Returns:
            Sentiment score from -1.0 (negative) to 1.0 (positive)
        """
        text_lower = text.lower()
        
        positive_score = 0
        negative_score = 0
        
        # Count positive and negative words
        if language in self.sentiment_words["positive"]:
            for word in self.sentiment_words["positive"][language]:
                positive_score += len(re.findall(r'\b' + re.escape(word) + r'\b', text_lower))
        
        if language in self.sentiment_words["negative"]:
            for word in self.sentiment_words["negative"][language]:
                negative_score += len(re.findall(r'\b' + re.escape(word) + r'\b', text_lower))
        
        # Calculate sentiment score
        total_words = positive_score + negative_score
        if total_words == 0:
            return 0.0
        
        sentiment = (positive_score - negative_score) / total_words
        return max(-1.0, min(1.0, sentiment))


# =============================================================================
# Main NLP Service
# =============================================================================

class NLPService:
    """
    Main NLP service that combines all analysis capabilities.
    
    Provides comprehensive text analysis for animal rescue reports including:
    - Language detection
    - Keyword extraction
    - Urgency detection
    - Animal classification
    - Sentiment analysis
    - Text similarity
    """
    
    def __init__(self):
        self.language_detector = LanguageDetector()
        self.keyword_extractor = KeywordExtractor()
        self.urgency_detector = UrgencyDetector()
        self.animal_classifier = AnimalClassifier()
        self.sentiment_analyzer = SentimentAnalyzer()
        
        logger.info("NLP Service initialized")
    
    @cached(ttl=3600, namespace="nlp")
    async def analyze_text(
        self, 
        text: str, 
        language: Optional[str] = None,
        include_similarity: bool = False
    ) -> Dict[str, Any]:
        """
        Perform comprehensive NLP analysis on text.
        
        Args:
            text: Text to analyze
            language: Language code (auto-detect if None)
            include_similarity: Whether to include similarity analysis
            
        Returns:
            Dictionary with analysis results
        """
        if not text or not text.strip():
            return self._empty_result()
        
        try:
            # Detect language if not provided
            if not language:
                language, lang_confidence = self.language_detector.detect_language(text)
            else:
                lang_confidence = 1.0
            
            # Extract keywords
            keywords_data = self.keyword_extractor.extract_keywords(text, language)
            all_keywords = []
            for category_keywords in keywords_data.values():
                all_keywords.extend(category_keywords)
            
            # Detect urgency level
            urgency_level, urgency_confidence = self.urgency_detector.detect_urgency(text, language)
            
            # Classify animal type
            animal_type, animal_confidence = self.animal_classifier.classify_animal(text, language)
            
            # Analyze sentiment
            sentiment_score = self.sentiment_analyzer.analyze_sentiment(text, language)
            
            # Calculate overall confidence
            overall_confidence = (
                lang_confidence * 0.2 +
                urgency_confidence * 0.3 +
                animal_confidence * 0.3 +
                (1.0 if all_keywords else 0.5) * 0.2
            )
            
            result = {
                "language": language,
                "language_confidence": lang_confidence,
                "urgency": urgency_level,
                "urgency_confidence": urgency_confidence,
                "animal_type": animal_type,
                "animal_confidence": animal_confidence,
                "keywords": all_keywords,
                "keywords_by_category": keywords_data,
                "sentiment": sentiment_score,
                "overall_confidence": overall_confidence,
                "text_length": len(text),
                "word_count": len(text.split()),
            }
            
            logger.debug(
                "NLP analysis completed",
                language=language,
                urgency=urgency_level.value,
                animal_type=animal_type.value,
                keyword_count=len(all_keywords),
                confidence=overall_confidence
            )
            
            return result
            
        except Exception as e:
            logger.error("NLP analysis failed", error=str(e), exc_info=True)
            return self._empty_result()
    
    async def analyze_report_content(
        self,
        text: str,
        language: str = "he",
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Analyze report content with additional context.
        
        Args:
            text: Report description
            language: Language code
            context: Additional context (location, urgency, etc.)
            
        Returns:
            Enhanced analysis results
        """
        # Perform basic analysis
        basic_analysis = await self.analyze_text(text, language)
        
        # Enhance with context if provided
        if context:
            # Boost urgency if location suggests danger
            if context.get("location") and any(
                danger_word in context["location"].lower()
                for danger_word in ["כביש", "highway", "road", "طريق"]
            ):
                if basic_analysis["urgency"] == UrgencyLevel.LOW:
                    basic_analysis["urgency"] = UrgencyLevel.MEDIUM
                elif basic_analysis["urgency"] == UrgencyLevel.MEDIUM:
                    basic_analysis["urgency"] = UrgencyLevel.HIGH
            
            # Add contextual keywords
            context_keywords = []
            if context.get("urgency"):
                context_keywords.append(f"context_urgency_{context['urgency']}")
            if context.get("animal_type"):
                context_keywords.append(f"context_animal_{context['animal_type']}")
            
            basic_analysis["keywords"].extend(context_keywords)
        
        return basic_analysis
    
    async def generate_title(self, description: str, language: str = "he") -> str:
        """
        Generate a title for a report based on its description.
        
        Args:
            description: Report description
            language: Language code
            
        Returns:
            Generated title
        """
        try:
            analysis = await self.analyze_text(description, language)
            
            # Title templates by language
            templates = {
                "he": {
                    UrgencyLevel.CRITICAL: "חירום: {animal} במצב קריטי",
                    UrgencyLevel.HIGH: "דחוף: {animal} זקוק לעזרה",
                    UrgencyLevel.MEDIUM: "{animal} זקוק לעזרה",
                    UrgencyLevel.LOW: "{animal} נמצא"
                },
                "ar": {
                    UrgencyLevel.CRITICAL: "طوارئ: {animal} في حالة حرجة",
                    UrgencyLevel.HIGH: "عاجل: {animal} يحتاج مساعدة",
                    UrgencyLevel.MEDIUM: "{animal} يحتاج مساعدة",
                    UrgencyLevel.LOW: "{animal} موجود"
                },
                "en": {
                    UrgencyLevel.CRITICAL: "Emergency: {animal} in critical condition",
                    UrgencyLevel.HIGH: "Urgent: {animal} needs help",
                    UrgencyLevel.MEDIUM: "{animal} needs help",
                    UrgencyLevel.LOW: "{animal} found"
                }
            }
            
            # Animal names by language
            animal_names = {
                "he": {
                    AnimalType.DOG: "כלב",
                    AnimalType.CAT: "חתול",
                    AnimalType.BIRD: "ציפור",
                    AnimalType.WILDLIFE: "חיית בר",
                    AnimalType.LIVESTOCK: "בעל חיים",
                    AnimalType.EXOTIC: "חיה אקזוטית",
                    AnimalType.OTHER: "בעל חיים",
                    AnimalType.UNKNOWN: "בעל חיים"
                },
                "ar": {
                    AnimalType.DOG: "كلب",
                    AnimalType.CAT: "قطة",
                    AnimalType.BIRD: "طائر",
                    AnimalType.WILDLIFE: "حيوان بري",
                    AnimalType.LIVESTOCK: "حيوان",
                    AnimalType.EXOTIC: "حيوان غريب",
                    AnimalType.OTHER: "حيوان",
                    AnimalType.UNKNOWN: "حيوان"
                },
                "en": {
                    AnimalType.DOG: "Dog",
                    AnimalType.CAT: "Cat",
                    AnimalType.BIRD: "Bird",
                    AnimalType.WILDLIFE: "Wild Animal",
                    AnimalType.LIVESTOCK: "Livestock",
                    AnimalType.EXOTIC: "Exotic Animal",
                    AnimalType.OTHER: "Animal",
                    AnimalType.UNKNOWN: "Animal"
                }
            }
            
            urgency = analysis.get("urgency", UrgencyLevel.MEDIUM)
            animal_type = analysis.get("animal_type", AnimalType.UNKNOWN)
            
            if language in templates and urgency in templates[language]:
                template = templates[language][urgency]
                animal_name = animal_names.get(language, {}).get(animal_type, "בעל חיים")
                title = template.format(animal=animal_name)
            else:
                # Fallback title
                title = description[:50] + "..." if len(description) > 50 else description
            
            return title
            
        except Exception as e:
            logger.error("Title generation failed", error=str(e))
            return description[:50] + "..." if len(description) > 50 else description
    
    async def calculate_text_similarity(
        self, 
        text1: str, 
        text2: str,
        language: str = "he"
    ) -> SimilarityResult:
        """
        Calculate similarity between two texts.
        
        Args:
            text1: First text
            text2: Second text
            language: Language code
            
        Returns:
            SimilarityResult object
        """
        try:
            # Extract keywords from both texts
            keywords1_data = self.keyword_extractor.extract_keywords(text1, language)
            keywords2_data = self.keyword_extractor.extract_keywords(text2, language)
            
            # Flatten keyword lists
            keywords1 = set()
            keywords2 = set()
            
            for category_keywords in keywords1_data.values():
                keywords1.update(keyword.lower() for keyword in category_keywords)
            
            for category_keywords in keywords2_data.values():
                keywords2.update(keyword.lower() for keyword in category_keywords)
            
            # Calculate Jaccard similarity
            intersection = keywords1 & keywords2
            union = keywords1 | keywords2
            
            if not union:
                jaccard_similarity = 0.0
            else:
                jaccard_similarity = len(intersection) / len(union)
            
            # Simple word-based similarity
            words1 = set(re.findall(r'\b\w+\b', text1.lower()))
            words2 = set(re.findall(r'\b\w+\b', text2.lower()))
            
            word_intersection = words1 & words2
            word_union = words1 | words2
            
            if not word_union:
                word_similarity = 0.0
            else:
                word_similarity = len(word_intersection) / len(word_union)
            
            # Combined similarity score
            similarity_score = (jaccard_similarity * 0.7 + word_similarity * 0.3)
            
            # Determine if texts are duplicates
            is_duplicate = similarity_score > 0.8
            confidence = similarity_score
            
            return SimilarityResult(
                similarity_score=similarity_score,
                matching_keywords=list(intersection),
                is_duplicate=is_duplicate,
                confidence=confidence
            )
            
        except Exception as e:
            logger.error("Text similarity calculation failed", error=str(e))
            return SimilarityResult(
                similarity_score=0.0,
                matching_keywords=[],
                is_duplicate=False,
                confidence=0.0
            )
    
    def _empty_result(self) -> Dict[str, Any]:
        """Return empty analysis result."""
        return {
            "language": "he",
            "language_confidence": 0.0,
            "urgency": UrgencyLevel.MEDIUM,
            "urgency_confidence": 0.0,
            "animal_type": AnimalType.UNKNOWN,
            "animal_confidence": 0.0,
            "keywords": [],
            "keywords_by_category": {"animals": [], "urgency": [], "location": [], "general": []},
            "sentiment": 0.0,
            "overall_confidence": 0.0,
            "text_length": 0,
            "word_count": 0,
        }
    
    async def get_service_stats(self) -> Dict[str, Any]:
        """Get NLP service statistics."""
        return {
            "service_name": "NLP Service",
            "supported_languages": ["he", "ar", "en"],
            "supported_animal_types": [animal.value for animal in AnimalType],
            "supported_urgency_levels": [urgency.value for urgency in UrgencyLevel],
            "features": [
                "Language Detection",
                "Keyword Extraction", 
                "Urgency Detection",
                "Animal Classification",
                "Sentiment Analysis",
                "Text Similarity",
                "Title Generation"
            ]
        }


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    "NLPService",
    "NLPResult",
    "SimilarityResult",
    "LanguageDetector",
    "KeywordExtractor",
    "UrgencyDetector",
    "AnimalClassifier",
    "SentimentAnalyzer",
]
