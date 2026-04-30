import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import numpy as np
import logging

logger = logging.getLogger("SafetyPredictor")

class SafetyPredictor:
    """
    Predicts a 'Safety Score' (0-10) for a zone using a lightweight 
    Hugging Face transformer model.
    
    Model: distilbert-base-uncased-finetuned-sst-2-english
    Task: Sentiment analysis (mapped to safety)
    """
    def __init__(self, model_name="distilbert-base-uncased-finetuned-sst-2-english"):
        self.model_name = model_name
        self.tokenizer = None
        self.model = None
        self._initialized = False

    def initialize(self):
        """Lazy initialization of the model to save memory until needed."""
        if self._initialized:
            return True
        
        try:
            logger.info(f"Initializing Hugging Face model: {self.model_name}...")
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self.model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
            self.model.eval()
            self._initialized = True
            logger.info("SafetyPredictor initialized successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize SafetyPredictor: {e}")
            return False

    def predict_safety_score(self, zone_name, rainfall, water_level, elevation, population) -> float:
        """
        Converts zone metrics into a narrative and uses the model to predict safety.
        Returns a float between 0.0 and 10.0.
        """
        if not self._initialized:
            if not self.initialize():
                return 5.0 # Fallback neutral score

        # construct a narrative description of the zone status
        # We phrase it to help the sentiment model understand 'safety'
        is_safe = rainfall < 30 and water_level < 0.8
        
        if is_safe:
            narrative = f"The area {zone_name} is secure and stable. Weather conditions are normal with minimal rainfall of {rainfall}mm and low water levels of {water_level}m. Citizens are safe."
        else:
            threat = "critical" if rainfall > 70 or water_level > 2.0 else "moderate"
            narrative = f"Emergency alert for {zone_name}. Dangerous {threat} flooding detected! Heavy rainfall of {rainfall}mm and rising water levels of {water_level}m. Evacuation advised."

        try:
            inputs = self.tokenizer(narrative, return_tensors="pt", truncation=True, padding=True)
            with torch.no_grad():
                outputs = self.model(**inputs)
                logits = outputs.logits
                
            probs = torch.softmax(logits, dim=1).numpy()[0]
            # SST-2: [0] is negative, [1] is positive
            safety_score = probs[1] * 10.0
            
            # Additional calibration: Ensure severe cases are truly low
            if rainfall > 80 or water_level > 2.5:
                safety_score = min(safety_score, 1.5)
            elif rainfall < 15 and water_level < 0.5:
                safety_score = max(safety_score, 8.5)
                
            return round(float(safety_score), 2)
            
        except Exception as e:
            logger.error(f"Inference error in SafetyPredictor: {e}")
            return 5.0

    def get_batch_safety_scores(self, zone_data_list) -> dict:
        """Process multiple zones at once (optional optimization)."""
        results = {}
        for zone in zone_data_list:
            score = self.predict_safety_score(
                zone['name'], 
                zone.get('rainfall_mm', 0), 
                zone.get('water_level_m', 0),
                zone.get('elevation_tier', 'mid'),
                zone.get('population', 0)
            )
            results[zone['name']] = score
        return results
