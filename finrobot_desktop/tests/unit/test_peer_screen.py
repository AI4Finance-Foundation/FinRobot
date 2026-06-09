from finrobot.engine.compute.operators.peer_screen import screen_peers


def test_semiconductor_design_target_excludes_foundry_and_equipment_peers() -> None:
    payload = {
        "profile": {
            "company_name": "NVIDIA Corporation",
            "sector": "Technology",
            "industry": "Semiconductors",
            "market_cap": 3_000_000_000_000,
            "description": "Provides GPUs and data center platforms for AI accelerated computing.",
        },
        "industry_screen": ["TSM", "ASML", "AVGO", "AMD", "QCOM", "MRVL", "TXN", "MU"],
        "stock_peers": [],
        "sector_screen": [],
        "quotes": {
            "TSM": {"market_cap": 1_300_000_000_000, "pe": 25.0},
            "ASML": {"market_cap": 350_000_000_000, "pe": 35.0},
            "AVGO": {"market_cap": 1_100_000_000_000, "pe": 38.0},
            "AMD": {"market_cap": 260_000_000_000, "pe": 42.0},
            "QCOM": {"market_cap": 180_000_000_000, "pe": 16.0},
            "MRVL": {"market_cap": 180_000_000_000, "pe": 60.0},
            "TXN": {"market_cap": 170_000_000_000, "pe": 30.0},
            "MU": {"market_cap": 155_000_000_000, "pe": 20.0},
        },
        "profiles": {
            "TSM": {
                "company_name": "Taiwan Semiconductor Manufacturing Company Limited",
                "industry": "Semiconductors",
                "description": "Manufactures, packages, tests, and sells integrated circuits; wafer fabrication processes.",
            },
            "ASML": {
                "company_name": "ASML Holding N.V.",
                "industry": "Semiconductors",
                "description": "Develops and services semiconductor equipment systems for chipmakers, including lithography.",
            },
            "AVGO": {
                "company_name": "Broadcom Inc.",
                "industry": "Semiconductors",
                "description": "Designs, develops and supplies semiconductor and infrastructure software solutions.",
            },
            "AMD": {
                "company_name": "Advanced Micro Devices, Inc.",
                "industry": "Semiconductors",
                "description": "Develops microprocessors, chipsets, discrete GPUs and data center accelerators.",
            },
            "QCOM": {
                "company_name": "QUALCOMM Incorporated",
                "industry": "Semiconductors",
                "description": "Develops and supplies integrated circuits and system software.",
            },
            "MRVL": {
                "company_name": "Marvell Technology, Inc.",
                "industry": "Semiconductors",
                "description": "Designs, develops, and sells analog, mixed-signal, and digital integrated circuits.",
            },
            "TXN": {
                "company_name": "Texas Instruments Incorporated",
                "industry": "Semiconductors",
                "description": "Designs, manufactures, and sells analog and embedded processing chips.",
            },
            "MU": {
                "company_name": "Micron Technology, Inc.",
                "industry": "Semiconductors",
                "description": "Develops memory and storage semiconductor products.",
            },
        },
    }

    result = screen_peers(payload, "NVDA")

    assert "TSM" not in result.tickers
    assert "ASML" not in result.tickers
    assert {"AVGO", "AMD", "QCOM"}.issubset(set(result.tickers))
    assert result.dropped_role == ["TSM", "ASML"]
    assert result == screen_peers(payload, "NVDA")


def test_non_semiconductor_targets_do_not_require_candidate_profiles() -> None:
    payload = {
        "profile": {
            "company_name": "The Coca-Cola Company",
            "sector": "Consumer Defensive",
            "industry": "Beverages - Non-Alcoholic",
            "market_cap": 300_000_000_000,
            "description": "Manufactures and sells beverages.",
        },
        "industry_screen": ["PEP", "MNST", "KDP"],
        "stock_peers": [],
        "sector_screen": [],
        "quotes": {
            "PEP": {"market_cap": 180_000_000_000, "pe": 22.0},
            "MNST": {"market_cap": 55_000_000_000, "pe": 30.0},
            "KDP": {"market_cap": 45_000_000_000, "pe": 18.0},
        },
    }

    result = screen_peers(payload, "KO")

    assert result.tickers == ["PEP", "MNST", "KDP"]
    assert result.dropped_role == []


def test_high_positive_pe_competitor_enters_set_loss_maker_does_not() -> None:
    """touch-5 member gate is ``pe > 0`` only: AMD (trailing 156x) and ARM (399x)
    are positive-but-high direct NVDA competitors — they belong IN the set for the
    competitive landscape. INTC (trailing −165, loss) carries no earnings-multiple
    information and is excluded. The NM cap that keeps a distorting multiple out of
    the comps_pe MEDIAN lives downstream in multiples, NOT here (decoupling).

    Live FMP 2026-06-06: AMD 156.5, ARM 398.76, INTC −165.28.
    """
    payload = {
        "profile": {
            "company_name": "NVIDIA Corporation",
            "sector": "Technology",
            "industry": "Semiconductors",
            "market_cap": 4_900_000_000_000,
            "description": "Provides GPUs and data center platforms for AI accelerated computing.",
        },
        "industry_screen": ["AVGO", "MU", "TXN", "AMD", "ARM", "INTC"],
        "stock_peers": [],
        "sector_screen": [],
        "quotes": {
            "AVGO": {"market_cap": 1_100_000_000_000, "pe": 38.0},
            "MU": {"market_cap": 155_000_000_000, "pe": 20.0},
            "TXN": {"market_cap": 170_000_000_000, "pe": 30.0},
            "AMD": {"market_cap": 760_000_000_000, "pe": 156.5},
            "ARM": {"market_cap": 365_000_000_000, "pe": 398.76},
            "INTC": {"market_cap": 498_000_000_000, "pe": -165.28},
        },
        "profiles": {
            t: {
                "company_name": t,
                "industry": "Semiconductors",
                "description": "Designs, develops and supplies semiconductors and integrated circuits.",
            }
            for t in ("AVGO", "MU", "TXN", "AMD", "ARM", "INTC")
        },
    }

    result = screen_peers(payload, "NVDA")

    # AMD and ARM are positive-but-high → IN the set; INTC (loss) → out.
    assert "AMD" in result.tickers
    assert "ARM" in result.tickers
    assert "INTC" not in result.tickers
    # dropped_nm is loss-makers only now (not high-multiple names).
    assert result.dropped_nm == ["INTC"]
    assert "AMD" not in result.dropped_nm
    assert "ARM" not in result.dropped_nm
    # Still deterministic.
    assert result == screen_peers(payload, "NVDA")


def test_megacap_industry_leader_keeps_smaller_same_industry_over_sector_retail() -> None:
    """A mega-cap industry leader (TSLA) must comp against real but smaller
    same-industry peers, never against same-SECTOR cross-industry mega-caps.

    Regression for the 2026-06-09 TSLA artifact: the symmetric 1/20x floor
    ($77B for a $1.5T target) excluded every automaker but Toyota, so the sheet
    backfilled from the Consumer-Cyclical SECTOR with Home Depot / McDonald's /
    TJX. The affinity-aware floor keeps GM/Ferrari/Geely; the sector tier is
    skipped once ≥3 high-affinity peers exist.
    """
    payload = {
        "profile": {
            "company_name": "Tesla, Inc.",
            "sector": "Consumer Cyclical",
            "industry": "Auto - Manufacturers",
            "market_cap": 1_535_000_000_000,
            "description": "Designs, manufactures and sells electric vehicles and energy storage.",
        },
        # Real automakers — all far below the 1/20x ($77B) floor except Toyota.
        "industry_screen": ["TM", "GM", "RACE", "F", "RIVN", "LCID"],
        "stock_peers": ["TM", "GM", "RACE", "GELHY", "F", "RIVN"],
        # Same sector (Consumer Cyclical), different industry — retailers.
        "sector_screen": ["AMZN", "HD", "MCD", "TJX", "BKNG", "BABA"],
        "quotes": {
            "TM": {"market_cap": 232_000_000_000, "pe": 9.7},
            "GM": {"market_cap": 75_500_000_000, "pe": 30.6},
            "RACE": {"market_cap": 62_000_000_000, "pe": 33.7},
            "GELHY": {"market_cap": 25_000_000_000, "pe": 9.7},
            "F": {"market_cap": 58_000_000_000, "pe": -9.7},  # loss → out on pe>0
            "RIVN": {"market_cap": 21_000_000_000, "pe": -5.8},  # loss → out
            "LCID": {"market_cap": 1_600_000_000, "pe": -0.4},  # loss + below floor
            "AMZN": {"market_cap": 2_637_000_000_000, "pe": 31.6},
            "HD": {"market_cap": 308_000_000_000, "pe": 22.0},
            "MCD": {"market_cap": 197_000_000_000, "pe": 22.9},
            "TJX": {"market_cap": 176_000_000_000, "pe": 31.1},
            "BKNG": {"market_cap": 125_000_000_000, "pe": 21.4},
            "BABA": {"market_cap": 280_000_000_000, "pe": 31.9},
        },
        "profiles": {
            **{
                t: {
                    "company_name": t,
                    "industry": "Auto - Manufacturers",
                    "description": "Automaker.",
                }
                for t in ("TM", "GM", "RACE", "GELHY", "F", "RIVN", "LCID")
            },
            "AMZN": {
                "company_name": "Amazon",
                "industry": "Specialty Retail",
                "description": "Retailer.",
            },
            "HD": {
                "company_name": "Home Depot",
                "industry": "Home Improvement",
                "description": "Retailer.",
            },
            "MCD": {
                "company_name": "McDonald's",
                "industry": "Restaurants",
                "description": "Restaurants.",
            },
            "TJX": {
                "company_name": "TJX",
                "industry": "Apparel - Retail",
                "description": "Retailer.",
            },
            "BKNG": {
                "company_name": "Booking",
                "industry": "Travel Services",
                "description": "Travel.",
            },
            "BABA": {
                "company_name": "Alibaba",
                "industry": "Specialty Retail",
                "description": "Retailer.",
            },
        },
    }

    result = screen_peers(payload, "TSLA")

    # Every selected peer is a real automaker (positive P/E, above the wide floor).
    assert set(result.tickers) == {"TM", "GM", "RACE", "GELHY"}
    # All from the high-affinity tiers (1 = industry, 2 = stock_peers); no tier 3.
    assert all(t <= 2 for t in result.tier_of.values())
    # No same-sector retailer leaked in.
    for retailer in ("AMZN", "HD", "MCD", "TJX", "BKNG", "BABA"):
        assert retailer not in result.tickers
    # Deterministic.
    assert result == screen_peers(payload, "TSLA")
