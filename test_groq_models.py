#!/usr/bin/env python3
"""
test_models.py
Validates API connectivity and model accessibility for the 4 target Groq models.
"""

import os
from groq import Groq

def main():
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("[FATAL ERROR] GROQ_API_KEY environment variable not found!")
        return

    client = Groq(api_key=api_key)

    # The 4 models highlighted in your Groq screenshot
    models_to_test = [
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "qwen/qwen3.6-27b",
        "qwen/qwen3.8-27b"
    ]

    print("================================================================")
    print(" GROQ API MODEL VALIDATION TEST")
    print("================================================================\n")

    success_count = 0

    for model_name in models_to_test:
        print(f"[*] Pinging Model: {model_name}...")
        try:
            response = client.chat.completions.create(
                messages=[
                    {"role": "user", "content": "Respond with exactly one word: 'Alive'"}
                ],
                model=model_name,
                temperature=0.0,
                max_tokens=10
            )
            
            output = response.choices[0].message.content.strip()
            print(f"    [SUCCESS] Received: {output}\n")
            success_count += 1
            
        except Exception as e:
            print(f"    [FAILED] Error details: {e}\n")

    print("================================================================")
    print(f" TEST COMPLETE: {success_count}/{len(models_to_test)} models successfully hit.")
    print("================================================================")

if __name__ == "__main__":
    main()
