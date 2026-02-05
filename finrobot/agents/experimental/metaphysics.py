"""
Financial Metaphysics Agent - WuXing Algorithm for Alternative Data Analysis.

This module implements an experimental agent that uses traditional Chinese
Astrology (Bazi/WuXing - Four Pillars of Destiny / Five Elements) to provide
"luck-based" market sentiment analysis.

DISCLAIMER:
-----------
This agent is provided for ENTERTAINMENT and RESEARCH purposes only.
It represents an exploration of "Alternative Data" using cultural frameworks.
The signals generated should NOT be used as the sole basis for any investment
decisions. Past celestial alignments do not guarantee future returns.
As the ancient sages say: "The stars impel, they do not compel."

Dependencies:
    - lunar_python: https://github.com/6tail/lunar-python
      Install via: pip install lunar_python

Author: FinRobot Contributors
License: MIT
"""

import datetime
from textwrap import dedent
from typing import Any, Dict, List, Optional, Tuple

from lunar_python import Lunar


class MetaphysicsUtils:
    """
    Utility class for Chinese Metaphysics (WuXing/Bazi) calculations.
    
    This class provides the core logic for:
    - Mapping market sectors to Five Elements (WuXing)
    - Calculating the dominant element of any given day
    - Analyzing element interactions (Generating/Overcoming cycles)
    
    The Five Elements (WuXing - 五行):
        Wood (木) - Growth, expansion
        Fire (火) - Energy, transformation
        Earth (土) - Stability, grounding
        Metal (金) - Contraction, refinement
        Water (水) - Flow, wisdom
    """

    # Chinese characters for elements
    ELEMENT_CHINESE: Dict[str, str] = {
        "Wood": "木",
        "Fire": "火",
        "Earth": "土",
        "Metal": "金",
        "Water": "水",
    }

    # Sector to Element Mapping
    # Based on traditional Chinese business element associations
    SECTOR_ELEMENT_MAP: Dict[str, str] = {
        # Fire (火) - Energy, Technology, Innovation
        "Technology": "Fire",
        "Energy": "Fire",
        "Semiconductors": "Fire",
        "Electronics": "Fire",
        "Media": "Fire",
        # Earth (土) - Real Estate, Mining, Construction
        "Real Estate": "Earth",
        "Mining": "Earth",
        "Construction": "Earth",
        "Materials": "Earth",
        "Infrastructure": "Earth",
        # Metal (金) - Finance, Precious Metals, Machinery
        "Finance": "Metal",
        "Banking": "Metal",
        "Insurance": "Metal",
        "Automotive": "Metal",
        "Aerospace": "Metal",
        # Water (水) - Logistics, Transport, Beverages
        "Logistics": "Water",
        "Transport": "Water",
        "Shipping": "Water",
        "Beverage": "Water",
        "Tourism": "Water",
        "Entertainment": "Water",
        # Wood (木) - Agriculture, Textiles, Healthcare
        "Agriculture": "Wood",
        "Textiles": "Wood",
        "Healthcare": "Wood",
        "Education": "Wood",
        "Publishing": "Wood",
    }

    # Generating Cycle (相生 - Xiangsheng) - Productive/Creative Cycle
    # The element in key GENERATES the element in value
    # Wood -> Fire -> Earth -> Metal -> Water -> Wood
    GENERATING_CYCLE: Dict[str, str] = {
        "Wood": "Fire",    # Wood feeds Fire
        "Fire": "Earth",   # Fire creates Earth (ash)
        "Earth": "Metal",  # Earth bears Metal
        "Metal": "Water",  # Metal collects Water
        "Water": "Wood",   # Water nourishes Wood
    }

    # Overcoming Cycle (相克 - Xiangke) - Destructive/Controlling Cycle
    # The element in key OVERCOMES/CONTROLS the element in value
    # Wood -> Earth -> Water -> Fire -> Metal -> Wood
    OVERCOMING_CYCLE: Dict[str, str] = {
        "Wood": "Earth",   # Wood parts Earth (roots)
        "Earth": "Water",  # Earth absorbs Water
        "Water": "Fire",   # Water extinguishes Fire
        "Fire": "Metal",   # Fire melts Metal
        "Metal": "Wood",   # Metal chops Wood
    }

    # Heavenly Stems (天干) to Element mapping
    STEM_ELEMENT_MAP: Dict[str, str] = {
        "甲": "Wood", "乙": "Wood",
        "丙": "Fire", "丁": "Fire",
        "戊": "Earth", "己": "Earth",
        "庚": "Metal", "辛": "Metal",
        "壬": "Water", "癸": "Water",
    }

    # Auspicious directions by element
    ELEMENT_DIRECTION: Dict[str, str] = {
        "Wood": "East",
        "Fire": "South",
        "Earth": "Center",
        "Metal": "West",
        "Water": "North",
    }

    # Lucky colors by element
    ELEMENT_COLOR: Dict[str, str] = {
        "Wood": "Green",
        "Fire": "Red",
        "Earth": "Yellow/Brown",
        "Metal": "White/Gold",
        "Water": "Black/Blue",
    }

    @classmethod
    def get_supported_sectors(cls) -> List[str]:
        """Returns a list of all supported market sectors."""
        return list(cls.SECTOR_ELEMENT_MAP.keys())

    @classmethod
    def get_element_from_sector(cls, sector: str) -> Optional[str]:
        """
        Returns the WuXing element for a given market sector.
        
        Args:
            sector: The market sector name (case-insensitive).
            
        Returns:
            The corresponding element name, or None if sector is not found.
        """
        # Try exact match first
        if sector in cls.SECTOR_ELEMENT_MAP:
            return cls.SECTOR_ELEMENT_MAP[sector]
        
        # Try case-insensitive match
        sector_lower = sector.lower()
        for key, value in cls.SECTOR_ELEMENT_MAP.items():
            if key.lower() == sector_lower:
                return value
        
        return None

    @classmethod
    def get_day_pillar(cls, date: datetime.date) -> Tuple[str, str]:
        """
        Returns the Day Pillar (日柱) for a given date.
        
        The Day Pillar consists of:
        - Day Stem (日干 - Heavenly Stem)
        - Day Branch (日支 - Earthly Branch)
        
        Args:
            date: The date to analyze.
            
        Returns:
            A tuple of (Day Stem, Day Branch) in Chinese characters.
        """
        # lunar_python expects datetime, not date
        dt = datetime.datetime.combine(date, datetime.time.min)
        lunar = Lunar.fromDate(dt)
        day_gan = lunar.getDayGan()  # Heavenly Stem
        day_zhi = lunar.getDayZhi()  # Earthly Branch
        return (day_gan, day_zhi)

    @classmethod
    def get_day_element(cls, date: datetime.date) -> str:
        """
        Returns the dominant element of the day based on the Day Stem.
        
        In Bazi (Four Pillars), the Day Stem represents the "Day Master"
        and is the primary indicator for daily energy.
        
        Args:
            date: The date to analyze.
            
        Returns:
            The element name (Wood, Fire, Earth, Metal, or Water).
        """
        day_gan, _ = cls.get_day_pillar(date)
        return cls.STEM_ELEMENT_MAP.get(day_gan, "Earth")  # Default to Earth

    @classmethod
    def analyze_interaction(
        cls, day_element: str, sector_element: str
    ) -> Dict[str, Any]:
        """
        Analyzes the interaction between the day element and sector element.
        
        Uses the Generating (相生) and Overcoming (相克) cycles to determine
        whether the day is auspicious for a given sector.
        
        Args:
            day_element: The element of the day (from Day Stem).
            sector_element: The element of the market sector.
            
        Returns:
            A dictionary containing:
            - score: Luck score from 0-100
            - signal: Trading signal (Buy/Positive, Neutral, Sell/Caution, Avoid)
            - relationship: Description of the elemental relationship
            - commentary: Detailed analysis in Daoist-Wall Street style
        """
        day_cn = cls.ELEMENT_CHINESE.get(day_element, "")
        sector_cn = cls.ELEMENT_CHINESE.get(sector_element, "")

        # Same element - Harmony
        if day_element == sector_element:
            return {
                "score": 75,
                "signal": "Neutral/Supportive",
                "relationship": "Harmony (比和)",
                "commentary": (
                    f"The Day Element {day_element} ({day_cn}) resonates with the "
                    f"Sector Element {sector_element} ({sector_cn}). "
                    "Like attracts like - expect stable, supportive conditions. "
                    "Neither bull nor bear dominates; the Dao flows gently."
                ),
            }

        # Day GENERATES Sector - Very Auspicious (Day supports Sector)
        if cls.GENERATING_CYCLE.get(day_element) == sector_element:
            return {
                "score": 92,
                "signal": "Buy/Positive",
                "relationship": f"Day generates Sector (相生: {day_cn}生{sector_cn})",
                "commentary": (
                    f"Highly Auspicious! {day_element} ({day_cn}) generates "
                    f"{sector_element} ({sector_cn}). "
                    f"The cosmic Qi flows favorably - {day_element} nurtures and "
                    f"empowers {sector_element} sectors today. "
                    "Consider this a green light from the Heavens. "
                    "As the ancients say: 'When the elements align, fortune follows.'"
                ),
            }

        # Sector GENERATES Day - Moderately Auspicious (Sector feeds Day)
        if cls.GENERATING_CYCLE.get(sector_element) == day_element:
            return {
                "score": 78,
                "signal": "Positive",
                "relationship": f"Sector generates Day (相生: {sector_cn}生{day_cn})",
                "commentary": (
                    f"Favorable conditions. {sector_element} ({sector_cn}) generates "
                    f"{day_element} ({day_cn}). "
                    "The sector gives energy to the day - a sign of outflow. "
                    "Profits may come, but watch for exhaustion patterns. "
                    "The Qi moves outward; harvest mindfully."
                ),
            }

        # Day OVERCOMES Sector - Challenging (Day controls Sector)
        if cls.OVERCOMING_CYCLE.get(day_element) == sector_element:
            return {
                "score": 38,
                "signal": "Sell/Caution",
                "relationship": f"Day overcomes Sector (相克: {day_cn}克{sector_cn})",
                "commentary": (
                    f"Caution advised. {day_element} ({day_cn}) overcomes "
                    f"{sector_element} ({sector_cn}). "
                    f"The day's energy suppresses {sector_element} sectors. "
                    "Expect headwinds, resistance at key levels, and potential "
                    "volatility. The Controlling Cycle suggests external pressures. "
                    "Defensive positioning recommended."
                ),
            }

        # Sector OVERCOMES Day - Unfavorable (Sector attacks Day)
        if cls.OVERCOMING_CYCLE.get(sector_element) == day_element:
            return {
                "score": 25,
                "signal": "Avoid",
                "relationship": f"Sector overcomes Day (相克: {sector_cn}克{day_cn})",
                "commentary": (
                    f"Unfavorable alignment. {sector_element} ({sector_cn}) overcomes "
                    f"{day_element} ({day_cn}). "
                    "The sector's energy clashes with the day's cosmic rhythm. "
                    "Like swimming against the current of the Yangtze - "
                    "possible but exhausting. Best to sit this one out. "
                    "Wait for more harmonious alignments."
                ),
            }

        # Default - Neutral (no direct relationship)
        return {
            "score": 55,
            "signal": "Neutral",
            "relationship": "Indirect (间接)",
            "commentary": (
                f"The Day Element {day_element} ({day_cn}) and Sector Element "
                f"{sector_element} ({sector_cn}) have no direct generative or "
                "controlling relationship. The market moves on mundane factors today. "
                "Consult your fundamental analysis - the stars are silent on this pairing."
            ),
        }


class MetaphysicsAgent:
    """
    Financial Metaphysics Agent for Alternative Data Analysis.
    
    This experimental agent uses traditional Chinese Astrology (Bazi/WuXing)
    to provide "luck-based" market sentiment analysis. It maps market sectors
    to the Five Elements and analyzes their interaction with the daily
    elemental energy derived from the Lunar calendar.
    
    This is meant to be a fun, innovative "Alternative Data" feature that
    adds diversity to standard technical/fundamental analysis tools.
    
    Example:
        >>> from finrobot.agents.experimental import MetaphysicsAgent
        >>> agent = MetaphysicsAgent()
        >>> result = agent.analyze_market_luck("2024-01-15", "Technology")
        >>> print(result["commentary"])
    
    Attributes:
        utils: Instance of MetaphysicsUtils for calculations.
        
    Note:
        This agent is for ENTERTAINMENT and RESEARCH purposes only.
        Do not use its signals as the sole basis for investment decisions.
    """

    def __init__(self) -> None:
        """Initialize the Metaphysics Agent."""
        self.utils = MetaphysicsUtils

    def analyze_market_luck(
        self, date: str, sector: str
    ) -> Dict[str, Any]:
        """
        Analyze the market luck for a specific sector on a given date.
        
        This method calculates the "luck score" by examining the relationship
        between the day's elemental energy (from the Bazi Day Pillar) and
        the sector's associated element.
        
        Args:
            date: Date string in 'YYYY-MM-DD' format.
            sector: Market sector name (e.g., 'Technology', 'Finance').
                   Use MetaphysicsUtils.get_supported_sectors() for full list.
                   
        Returns:
            A dictionary containing:
            - date: The analyzed date
            - day_pillar: The Bazi Day Pillar (日柱) in Chinese
            - day_element: The element of the day
            - sector: The analyzed sector
            - sector_element: The element of the sector
            - luck_score: Score from 0-100 (higher is more auspicious)
            - signal: Trading signal (Buy/Positive, Neutral, Sell/Caution, Avoid)
            - relationship: The elemental relationship description
            - auspicious_direction: Lucky direction for the day
            - lucky_color: Lucky color for the day
            - commentary: Detailed Daoist-Wall Street style analysis
            
        Raises:
            ValueError: If date format is invalid or sector is not supported.
            
        Example:
            >>> agent = MetaphysicsAgent()
            >>> result = agent.analyze_market_luck("2024-01-15", "Technology")
            >>> print(f"Luck Score: {result['luck_score']}")
            >>> print(f"Signal: {result['signal']}")
        """
        # Validate and parse date
        try:
            date_obj = datetime.datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError as e:
            raise ValueError(
                f"Invalid date format '{date}'. Please use YYYY-MM-DD format."
            ) from e

        # Validate sector
        sector_element = self.utils.get_element_from_sector(sector)
        if sector_element is None:
            supported = ", ".join(self.utils.get_supported_sectors())
            raise ValueError(
                f"Unknown sector '{sector}'. Supported sectors: {supported}"
            )

        # Get day information
        day_gan, day_zhi = self.utils.get_day_pillar(date_obj)
        day_pillar = f"{day_gan}{day_zhi}"
        day_element = self.utils.get_day_element(date_obj)
        
        # Get element interaction analysis
        analysis = self.utils.analyze_interaction(day_element, sector_element)
        
        # Get auspicious direction and color for the day
        auspicious_direction = self.utils.ELEMENT_DIRECTION.get(day_element, "Center")
        lucky_color = self.utils.ELEMENT_COLOR.get(day_element, "Yellow")
        
        # Get Chinese characters for elements
        day_cn = self.utils.ELEMENT_CHINESE.get(day_element, "")
        sector_cn = self.utils.ELEMENT_CHINESE.get(sector_element, "")

        # Build comprehensive commentary
        full_commentary = dedent(f"""
            ══════════════════════════════════════════════════════════════
            ⛩️  FINANCIAL METAPHYSICS AGENT - MARKET LUCK ANALYSIS  ⛩️
            ══════════════════════════════════════════════════════════════
            
            Date: {date}
            Lunar Day Pillar (日柱): {day_pillar}
            Day Element: {day_element} ({day_cn})
            
            Sector: {sector}
            Sector Element: {sector_element} ({sector_cn})
            
            ──────────────────────────────────────────────────────────────
            ELEMENTAL RELATIONSHIP: {analysis['relationship']}
            ──────────────────────────────────────────────────────────────
            
            LUCK SCORE: {analysis['score']}/100
            SIGNAL: {analysis['signal']}
            
            ──────────────────────────────────────────────────────────────
            DAOIST MARKET COMMENTARY:
            ──────────────────────────────────────────────────────────────
            {analysis['commentary']}
            
            ──────────────────────────────────────────────────────────────
            FENG SHUI TRADING TIPS:
            ──────────────────────────────────────────────────────────────
            • Auspicious Direction: {auspicious_direction}
              (Face this direction while making trading decisions)
            • Lucky Color: {lucky_color}
              (Wear or display this color for enhanced Qi flow)
            
            ══════════════════════════════════════════════════════════════
            DISCLAIMER: This analysis is based on traditional Chinese
            metaphysics and is provided for entertainment purposes only.
            The Dao of investing requires wisdom beyond the stars.
            "The sage acts without action, teaches without words."
            ══════════════════════════════════════════════════════════════
        """).strip()

        return {
            "date": date,
            "day_pillar": day_pillar,
            "day_element": day_element,
            "day_element_cn": day_cn,
            "sector": sector,
            "sector_element": sector_element,
            "sector_element_cn": sector_cn,
            "luck_score": analysis["score"],
            "signal": analysis["signal"],
            "relationship": analysis["relationship"],
            "auspicious_direction": auspicious_direction,
            "lucky_color": lucky_color,
            "commentary": full_commentary,
        }

    def get_lucky_sectors(self, date: str) -> List[Dict[str, Any]]:
        """
        Get all sectors ranked by luck score for a given date.
        
        Analyzes all supported sectors and returns them sorted by
        luck score (highest first).
        
        Args:
            date: Date string in 'YYYY-MM-DD' format.
            
        Returns:
            List of analysis dictionaries, sorted by luck_score descending.
            
        Example:
            >>> agent = MetaphysicsAgent()
            >>> lucky = agent.get_lucky_sectors("2024-01-15")
            >>> print(f"Luckiest sector: {lucky[0]['sector']} ({lucky[0]['luck_score']})")
        """
        results = []
        for sector in self.utils.get_supported_sectors():
            try:
                analysis = self.analyze_market_luck(date, sector)
                results.append({
                    "sector": sector,
                    "element": analysis["sector_element"],
                    "luck_score": analysis["luck_score"],
                    "signal": analysis["signal"],
                })
            except ValueError:
                continue
        
        # Sort by luck_score descending
        results.sort(key=lambda x: x["luck_score"], reverse=True)
        return results

    def get_daily_report(self, date: str) -> str:
        """
        Generate a comprehensive daily luck report for all sectors.
        
        Args:
            date: Date string in 'YYYY-MM-DD' format.
            
        Returns:
            A formatted string report showing all sectors ranked by luck.
            
        Example:
            >>> agent = MetaphysicsAgent()
            >>> print(agent.get_daily_report("2024-01-15"))
        """
        try:
            date_obj = datetime.datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            return f"Error: Invalid date format '{date}'. Please use YYYY-MM-DD."

        day_gan, day_zhi = self.utils.get_day_pillar(date_obj)
        day_element = self.utils.get_day_element(date_obj)
        day_cn = self.utils.ELEMENT_CHINESE.get(day_element, "")
        
        ranked_sectors = self.get_lucky_sectors(date)
        
        # Build report
        lines = [
            "╔════════════════════════════════════════════════════════════════╗",
            "║   ⛩️  DAILY METAPHYSICS MARKET REPORT  ⛩️                      ║",
            "╠════════════════════════════════════════════════════════════════╣",
            f"║  Date: {date}                                              ║",
            f"║  Day Pillar: {day_gan}{day_zhi} | Element: {day_element} ({day_cn})                    ║",
            "╠════════════════════════════════════════════════════════════════╣",
            "║  SECTOR RANKINGS BY COSMIC ALIGNMENT                          ║",
            "╠════════════════════════════════════════════════════════════════╣",
        ]
        
        for i, sector_data in enumerate(ranked_sectors, 1):
            score = sector_data["luck_score"]
            signal = sector_data["signal"]
            sector = sector_data["sector"]
            element = sector_data["element"]
            
            # Determine emoji based on score
            if score >= 80:
                emoji = "🔥"
            elif score >= 60:
                emoji = "✨"
            elif score >= 40:
                emoji = "☁️"
            else:
                emoji = "⚠️"
            
            line = f"║  {i:2}. {emoji} {sector:<15} ({element:<5}) | Score: {score:3} | {signal:<15} ║"
            lines.append(line)
        
        lines.extend([
            "╠════════════════════════════════════════════════════════════════╣",
            "║  🔥 = Highly Auspicious  ✨ = Favorable                        ║",
            "║  ☁️ = Neutral           ⚠️ = Caution                          ║",
            "╚════════════════════════════════════════════════════════════════╝",
        ])
        
        return "\n".join(lines)


# Main execution for testing
if __name__ == "__main__":
    import sys
    
    agent = MetaphysicsAgent()
    
    # Default to today's date
    test_date = datetime.date.today().strftime("%Y-%m-%d")
    if len(sys.argv) > 1:
        test_date = sys.argv[1]
    
    print("\n" + "=" * 70)
    print("FINANCIAL METAPHYSICS AGENT - DEMO")
    print("=" * 70 + "\n")
    
    # Test single sector analysis
    print(">>> Single Sector Analysis: Technology")
    print("-" * 70)
    result = agent.analyze_market_luck(test_date, "Technology")
    print(result["commentary"])
    
    print("\n")
    
    # Test daily report
    print(">>> Daily Luck Report")
    print("-" * 70)
    print(agent.get_daily_report(test_date))
