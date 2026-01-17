#!/usr/bin/env python3
"""List audio-capable models on OpenRouter sorted by price."""

import json
import sys

try:
    import requests
except ImportError:
    print("Installing requests...", file=sys.stderr)
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests


def main():
    print("Fetching models from OpenRouter...")
    response = requests.get("https://openrouter.ai/api/v1/models", timeout=30)
    response.raise_for_status()
    data = response.json()
    
    # Filter for audio-capable models
    audio_models = []
    for model in data.get("data", []):
        input_modalities = model.get("architecture", {}).get("input_modalities", [])
        if "audio" in input_modalities:
            pricing = model.get("pricing", {})
            prompt_price = float(pricing.get("prompt", "999999"))
            completion_price = float(pricing.get("completion", "999999"))
            total_price = prompt_price + completion_price
            
            audio_models.append({
                "id": model.get("id"),
                "name": model.get("name"),
                "prompt_price": prompt_price,
                "completion_price": completion_price,
                "total_price": total_price,
                "free": prompt_price == 0 and completion_price == 0,
                "context_length": model.get("context_length", 0),
            })
    
    # Sort by total price (free first, then cheapest)
    audio_models.sort(key=lambda x: (not x["free"], x["total_price"]))
    
    # Print top 15 cheapest
    print("\n" + "=" * 100)
    print("Top 15 Cheapest Audio-Capable Models on OpenRouter")
    print("=" * 100)
    
    for i, model in enumerate(audio_models[:15], 1):
        free_tag = " [FREE]" if model["free"] else ""
        print(f"\n{i}. {model['id']}{free_tag}")
        print(f"   Name: {model['name']}")
        if model["free"]:
            print(f"   Cost: FREE")
        else:
            print(f"   Prompt: ${model['prompt_price']:.10f}/1K tokens")
            print(f"   Completion: ${model['completion_price']:.10f}/1K tokens")
            print(f"   Total (1K prompt + 1K completion): ${model['total_price']:.10f}")
        print(f"   Context: {model['context_length']:,} tokens")
    
    print("\n" + "=" * 100)
    print(f"\nTotal audio-capable models found: {len(audio_models)}")
    
    # Show free models separately
    free_models = [m for m in audio_models if m["free"]]
    if free_models:
        print(f"\nFree models ({len(free_models)}):")
        for model in free_models:
            print(f"  - {model['id']} ({model['name']})")


if __name__ == "__main__":
    main()
