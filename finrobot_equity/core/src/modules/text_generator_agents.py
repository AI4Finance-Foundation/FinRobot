#!/usr/bin/env python
# coding: utf-8

import os
import json
import logging
import urllib.request
import urllib.error
try:
    import pandas as pd
except ImportError:
    pd = None

from typing import Dict, List, Optional, Any

from modules.retail_sentiment_client import format_retail_sentiment_for_prompt

logger = logging.getLogger(__name__)


def _get_fallback_text(prompt_type: str, company_name: str) -> str:
    """Returns fallback text when agent generation fails."""
    fallbacks = {
        "tagline": f"{company_name} demonstrates strong financial fundamentals with consistent revenue growth and solid profitability metrics. The company maintains a competitive position in its market segment through operational efficiency and strategic initiatives. Strong balance sheet metrics support continued value creation for shareholders.",
        "company_overview": f"{company_name} operates as a prominent player in its industry sector, demonstrating consistent financial performance through strategic market positioning and operational excellence. The company has shown resilient growth patterns supported by strong demand dynamics and effective cost management strategies.",
        "investment_overview": f"{company_name} has delivered solid financial performance in recent periods, supported by strong operational execution and favorable market conditions. Revenue growth has been driven by robust demand and strategic initiatives, while margin improvements reflect operational efficiency gains.",
        "valuation_overview": f"{company_name} trades at reasonable valuation levels relative to its peer group, supported by strong fundamental metrics and growth prospects. The company's financial profile demonstrates consistent profitability and cash generation capabilities.",
        "risks": "Key risks include: (1) Industry competition and market share pressure, (2) Regulatory changes affecting operations, (3) Economic downturns impacting demand, (4) Technology disruption risks, (5) Supply chain and operational challenges.",
        "competitor_analysis": f"{company_name} demonstrates competitive positioning within its industry through consistent financial performance and strategic market positioning relative to key competitors in the sector.",
        "major_takeaways": f"Revenue Growth: {company_name}'s revenue growth shows consistent performance trends.\n\nGross Profit Margin: {company_name}'s gross profit margins demonstrate operational effectiveness.\n\nSG&A Expense Margin: {company_name}'s SG&A expense management shows disciplined cost control.\n\nEBITDA Margin Stability: {company_name}'s EBITDA margin stability reflects strong underlying fundamentals.",
        "news_summary": f"Recent news coverage for {company_name} reflects ongoing market interest and developments in the company's operations and strategic initiatives."
    }
    return fallbacks.get(prompt_type, f"{company_name} analysis for {prompt_type.replace('_', ' ')} section.")


# System prompts for each text section
SYSTEM_PROMPTS = {
    "tagline": "You are an equity research analyst. Create a 3-sentence professional tagline summarizing the company's financial position. Be concise and professional. Do not use markdown.",
    "company_overview": "You are a financial analyst. Write a comprehensive company overview (300-400 words) covering business model, products/services, market position, and recent performance. Use plain text, no markdown.",
    "investment_overview": "You are an investment analyst. Write an investment update (200-300 words) covering recent financial performance, growth drivers, and outlook. Use plain text, no markdown.",
    "valuation_overview": "You are a valuation analyst. Write a valuation analysis (200-300 words) covering current valuation metrics, peer comparison, and fair value assessment. Use plain text, no markdown.",
    "risks": "You are a risk analyst. List 5 key investment risks in bullet point format. Be specific and concise.",
    "competitor_analysis": "You are a competitive analyst. Write a competitor analysis (200-300 words) comparing the company to its peers. Use plain text, no markdown.",
    "major_takeaways": "You are a financial analyst. Provide 4 major takeaways covering: Revenue Growth, Gross Profit Margin, SG&A Expense Margin, and EBITDA Margin. Format each with a header followed by 1-2 sentences.",
    "news_summary": "You are a financial news analyst. Summarize the recent news (200-300 words) highlighting key developments and their investment implications. Use plain text, no markdown."
}


def _df_to_string(df: Any, name: str) -> str:
    """Converts a DataFrame to a markdown string for use in a prompt."""
    if df is None or (hasattr(df, 'empty') and df.empty):
        return f"{name}:\n[Data not available]\n"
    
    try:
        if hasattr(df, 'to_markdown'):
            return f"{name}:\n{df.to_markdown()}\n"
        return f"{name}:\n{str(df)}\n"
    except Exception as e:
        return f"{name}:\n[Error formatting data: {e}]\n"


def _prepare_user_prompt(data: Dict, prompt_type: str, company_name: str, company_ticker: str) -> str:
    """Prepare user prompt with financial data."""
    financial_metrics = data.get('financial_metrics')
    peer_ebitda = data.get('peer_ebitda')
    peer_ev_ebitda = data.get('peer_ev_ebitda')
    company_news = data.get('company_news')
    retail_sentiment = data.get('retail_sentiment')
    
    prompt = f"Company: {company_name} ({company_ticker})\n\n"
    
    if financial_metrics is not None and not financial_metrics.empty:
        prompt += _df_to_string(financial_metrics, "Financial Metrics")
    
    if peer_ebitda is not None and not peer_ebitda.empty:
        prompt += _df_to_string(peer_ebitda, "Peer EBITDA Comparison")
        
    if peer_ev_ebitda is not None and not peer_ev_ebitda.empty:
        prompt += _df_to_string(peer_ev_ebitda, "Peer EV/EBITDA Comparison")
    
    if prompt_type == "news_summary" and company_news:
        prompt += f"\n## Recent News:\n"
        for i, article in enumerate(company_news[:10], 1):  # Limit to 10 articles
            prompt += f"{i}. {article.get('title', 'N/A')} ({article.get('publishedDate', 'N/A')[:10]})\n"
            prompt += f"   {article.get('text', 'N/A')[:200]}...\n\n"

    if prompt_type == "news_summary" and retail_sentiment:
        prompt += "\n" + format_retail_sentiment_for_prompt(retail_sentiment) + "\n"

    prompt += f"\nPlease provide the {prompt_type.replace('_', ' ')} based on the above data."
    return prompt


def _call_gemini_rest_api(api_key: str, system_prompt: str, user_prompt: str, model: str = "gemini-2.5-flash", base_url: str = None) -> Optional[str]:
    """Calls Gemini REST API directly using standard urllib."""
    model_name = model.replace("models/", "") if model else "gemini-2.5-flash"
    
    # Handle base URL
    if base_url and "googleapis.com" in base_url and not base_url.endswith("/openai/") and not base_url.endswith("/openai"):
        endpoint = f"{base_url.rstrip('/')}/models/{model_name}:generateContent?key={api_key}"
    else:
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"

    payload = {
        "system_instruction": {
            "parts": [{"text": system_prompt}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": user_prompt}]
            }
        ],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 1000
        }
    }
    
    try:
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            candidates = data.get("candidates", [])
            if candidates and "content" in candidates[0] and "parts" in candidates[0]["content"]:
                parts = candidates[0]["content"]["parts"]
                if parts and "text" in parts[0]:
                    return parts[0]["text"].strip()
    except Exception as e:
        logger.warning(f"Gemini REST call with system_instruction failed: {e}, retrying without system_instruction...")
        # Retry with combined prompt if system_instruction is not supported for older models
        try:
            fallback_payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": f"Instructions:\n{system_prompt}\n\nTask:\n{user_prompt}"}]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.7,
                    "maxOutputTokens": 1000
                }
            }
            req = urllib.request.Request(
                endpoint,
                data=json.dumps(fallback_payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                candidates = data.get("candidates", [])
                if candidates and "content" in candidates[0] and "parts" in candidates[0]["content"]:
                    parts = candidates[0]["content"]["parts"]
                    if parts and "text" in parts[0]:
                        return parts[0]["text"].strip()
        except Exception as retry_err:
            logger.error(f"Gemini REST direct call error: {retry_err}")
            raise retry_err
    return None


import re

def _clean_model_output(text: str) -> str:
    """Removes thinking/reasoning tags and leading thinking artifacts from model outputs."""
    if not text:
        return text
    # Remove <think>...</think> tags if any
    cleaned = re.sub(r'<think>[\s\S]*?</think>', '', text).strip()
    return cleaned


def generate_text_section(
    data: Dict, 
    prompt_type: str, 
    api_key: str = None, 
    company_name: str = "", 
    company_ticker: str = "", 
    base_url: str = None, 
    model: str = None,
    service: str = "openai"
) -> str:
    """
    Generates a specific text section for the equity report using OpenAI, NVIDIA, or Gemini API.
    
    Args:
        data: Financial data dictionary
        prompt_type: Type of text section to generate
        api_key: API key for the selected service
        company_name: Company name
        company_ticker: Stock ticker
        base_url: Optional API base URL
        model: Optional model name
        service: AI provider/service ('openai', 'nvidia', 'gemini')
    """
    selected_service = (service or "openai").strip().lower()
    if selected_service in ["google", "google_gemini", "gemini_ai"]:
        selected_service = "gemini"
    elif selected_service in ["nv", "nvidia_nim", "nim"]:
        selected_service = "nvidia"
    
    print(f"🤖 Generating '{prompt_type}' text section using {selected_service.upper()}...")
    
    # Validate API key
    if not api_key:
        print(f"⚠️ Warning: No {selected_service.upper()} API key provided. Using fallback text for '{prompt_type}'.")
        return _get_fallback_text(prompt_type, company_name)
    
    # Get system prompt & user prompt
    system_prompt = SYSTEM_PROMPTS.get(prompt_type, f"You are a financial analyst. Provide {prompt_type.replace('_', ' ')} analysis.")
    user_prompt = _prepare_user_prompt(data, prompt_type, company_name, company_ticker)
    
    # Provider 1: Google Gemini
    if selected_service == "gemini":
        gemini_model = model or "gemini-2.5-flash"
        gemini_base_url = base_url or "https://generativelanguage.googleapis.com/v1beta/openai/"
        
        # Clean invalid placeholder URLs (e.g. https://gemini.api.ai)
        if "gemini.api.ai" in gemini_base_url:
            gemini_base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
            
        print(f"🤖 Using Gemini model: {gemini_model}")
        
        # Method 1: Try OpenAI-compatible endpoint
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url=gemini_base_url, timeout=60.0)
            response = client.chat.completions.create(
                model=gemini_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_tokens=2048
            )
            raw_text = response.choices[0].message.content or ""
            generated_text = _clean_model_output(raw_text)
            if generated_text:
                print(f"✅ Successfully generated '{prompt_type}' via Gemini ({len(generated_text)} chars)")
                return generated_text
        except Exception as e_openai:
            logger.info(f"Gemini OpenAI compatibility call attempt note: {e_openai}. Falling back to direct Gemini REST API...")
            
        # Method 2: Try direct Gemini REST API
        try:
            raw_text = _call_gemini_rest_api(
                api_key=api_key, 
                system_prompt=system_prompt, 
                user_prompt=user_prompt, 
                model=gemini_model, 
                base_url=gemini_base_url
            ) or ""
            generated_text = _clean_model_output(raw_text)
            if generated_text:
                print(f"✅ Successfully generated '{prompt_type}' via Gemini REST ({len(generated_text)} chars)")
                return generated_text
        except Exception as e_rest:
            print(f"❌ Error generating '{prompt_type}' with Gemini API: {e_rest}")
            return _get_fallback_text(prompt_type, company_name)
            
        return _get_fallback_text(prompt_type, company_name)

    # Provider 2: NVIDIA NIM
    elif selected_service == "nvidia":
        nvidia_model = model or "nvidia/nemotron-3.5-lightning-30b-a3b"
        nvidia_base_url = base_url or "https://integrate.api.nvidia.com/v1"
        print(f"🤖 Using NVIDIA model: {nvidia_model}")
        print(f"📡 Using NVIDIA base URL: {nvidia_base_url}")
        
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url=nvidia_base_url, timeout=60.0)
            response = client.chat.completions.create(
                model=nvidia_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_tokens=2048
            )
            raw_text = response.choices[0].message.content or ""
            generated_text = _clean_model_output(raw_text)
            if generated_text:
                print(f"✅ Successfully generated '{prompt_type}' via NVIDIA ({len(generated_text)} chars)")
                return generated_text
            else:
                print(f"⚠️ Warning: Empty response from NVIDIA for '{prompt_type}'")
                return _get_fallback_text(prompt_type, company_name)
        except Exception as e:
            print(f"❌ Error generating '{prompt_type}' with NVIDIA API: {e}")
            return _get_fallback_text(prompt_type, company_name)

    # Provider 3: OpenAI (default)
    else:
        openai_model = model or "gpt-4.1-mini"
        print(f"🤖 Using OpenAI model: {openai_model}")
        
        try:
            from openai import OpenAI
            client_kwargs = {"api_key": api_key, "timeout": 60.0}
            if base_url:
                client_kwargs["base_url"] = base_url
                print(f"📡 Using OpenAI base URL: {base_url}")
                
            client = OpenAI(**client_kwargs)
            response = client.chat.completions.create(
                model=openai_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_tokens=2048
            )
            raw_text = response.choices[0].message.content or ""
            generated_text = _clean_model_output(raw_text)
            if generated_text:
                print(f"✅ Successfully generated '{prompt_type}' via OpenAI ({len(generated_text)} chars)")
                return generated_text
            else:
                print(f"⚠️ Warning: Empty response from OpenAI for '{prompt_type}'")
                return _get_fallback_text(prompt_type, company_name)
        except Exception as e:
            print(f"❌ Error generating '{prompt_type}' with OpenAI API: {e}")
            return _get_fallback_text(prompt_type, company_name)


# Backward compatibility - keep old function signature
def _query_openai(prompt: str, api_key: str) -> str:
    """Legacy function for backward compatibility."""
    return "Text generation now handled by agents."


if __name__ == '__main__':
    print("Testing agent-based text_generator...")
