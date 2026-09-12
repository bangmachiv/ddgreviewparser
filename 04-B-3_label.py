#!/usr/bin/env python3
"""
04-B-3_label.py (DUMMY TEST MODE)
Tests the Groq API connection, 20s timeouts, and fallback logic for sentiment labeling.
Executes a 5-sequence test of the (OSS1 -> OSS2) x 3 retry loop.
"""

import builtins
import os
import time
from groq import Groq

# ---------------------------------------------------------------------------
# Global Print Override for Real-Time CI/CD Streaming
# ---------------------------------------------------------------------------
def print(*args, **kwargs):
    kwargs['flush'] = True
    builtins.print(*args, **kwargs)

# ---------------------------------------------------------------------------
# API Setup
# ---------------------------------------------------------------------------
API_KEY = os.environ.get("GROQ_API_KEY")
if not API_KEY:
    print("[ERROR] GROQ_API_KEY environment variable not found!")
    exit(1)

# Initialize Groq Client with a strict 20-second timeout at the network level
client = Groq(
    api_key=API_KEY,
    timeout=20.0,
    max_retries=0 # Disabling built-in retries to enforce custom fallback logic
)

PRIMARY_MODEL = "openai/gpt-oss-120b"
BACKUP_MODEL = "openai/gpt-oss-20b"

def test_oss_extraction(sequence_num):
    prompt = """
    You are a data labeling assistant. Read the review star rating and output a JSON object classifying the sentiment. 
    Map 1 to 2.5 stars as "NEGATIVE", 3 as "MIXED", and 3.5 to 5 as "POSITIVE".
    Rating: 1.5
    Output ONLY valid JSON in this format: {"sentiment_category": "LABEL"}
    """

    max_attempts = 3

    for attempt in range(1, max_attempts + 1):
        print(f"\n  [Sequence {sequence_num}] Attempt {attempt}/{max_attempts}")
        
        # Loop through our OSS hierarchy (OSS1 -> OSS2)
        for model_name in [PRIMARY_MODEL, BACKUP_MODEL]:
            print(f"      [Attempting Model: {model_name}]")
            try:
                response = client.chat.completions.create(
                    messages=[
                        {"role": "user", "content": prompt.strip()}
                    ],
                    model=model_name,
                    max_tokens=200,      # Strict 200 token limit applied
                    temperature=0.0      # Zero temperature for deterministic JSON output
                )
                
                result = response.choices[0].message.content.strip()
                print(f"      [SUCCESS on {model_name}] -> {result}")
                return True
                
            except Exception as e:
                print(f"      [FAILED on {model_name}]: {str(e)}")

        if attempt < max_attempts:
            print("      [Both models failed. Waiting 2 seconds before next attempt...]")
            time.sleep(2)

    print("      [FATAL] All retries exhausted. Sequence failed.")
    return False

def main():
    print("================================================================================")
    print(" STARTING OSS DUMMY TEST: (OSS1 -> OSS2) x 3 LOGIC")
    print("================================================================================")

    for i in range(1, 6):
        test_oss_extraction(i)
        # 2.5-second pacing protects against the 30 RPM (1 request per 2 seconds) limit
        print("  [Pacing] Waiting 2.5 seconds to respect 30 RPM limit...")
        time.sleep(2.5) 

    print("\n================================================================================")
    print(" DUMMY TEST COMPLETE")
    print("================================================================================")

if __name__ == "__main__":
    main()
