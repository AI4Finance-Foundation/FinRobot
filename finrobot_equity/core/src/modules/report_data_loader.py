#!/usr/bin/env python
# coding: utf-8

import pandas as pd
import os

def load_analysis_csv(csv_path: str) -> pd.DataFrame | None:
    """Loads the financial analysis data from a CSV file."""
    try:
        if not os.path.exists(csv_path):
            print(f"Error: Analysis CSV file not found at {csv_path}")
            return None
        df = pd.read_csv(csv_path)
        return df
    except Exception as e:
        print(f"Error loading analysis CSV from {csv_path}: {e}")
        return None

def load_text_from_file(file_path: str) -> str | None:
    """Loads text content from a specified file."""
    try:
        if not os.path.exists(file_path):
            print(f"Warning: Text file not found at {file_path}. Returning empty string.")
            return "" # Return empty string or None, depending on desired handling
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return content
    except Exception as e:
        print(f"Error loading text from {file_path}: {e}")
        return None

if __name__ == "__main__":
    print("Testing report_data_loader.py...")
    # Create dummy files for testing
    dummy_csv_path = os.path.join(os.path.dirname(__file__), "dummy_analysis.csv")
    dummy_text_path = os.path.join(os.path.dirname(__file__), "dummy_text.txt")

    # Create dummy CSV
    dummy_df = pd.DataFrame({"metric": ["Revenue"], "2023A": [1000]})
    dummy_df.to_csv(dummy_csv_path, index=False)
    print(f"Created dummy CSV: {dummy_csv_path}")

    # Create dummy text file
    with open(dummy_text_path, "w") as f:
        f.write("This is a test overview.")
    print(f"Created dummy text file: {dummy_text_path}")

    # Test loading CSV
    loaded_df = load_analysis_csv(dummy_csv_path)
    if loaded_df is not None:
        print("\nLoaded DataFrame:")
        print(loaded_df)
    
    # Test loading text
    loaded_text = load_text_from_file(dummy_text_path)
    if loaded_text is not None:
        print("\nLoaded Text:")
        print(loaded_text)

    # Clean up dummy files
    if os.path.exists(dummy_csv_path):
        os.remove(dummy_csv_path)
        print(f"Cleaned up {dummy_csv_path}")
    if os.path.exists(dummy_text_path):
        os.remove(dummy_text_path)
        print(f"Cleaned up {dummy_text_path}")

    print("report_data_loader.py tests complete.")

