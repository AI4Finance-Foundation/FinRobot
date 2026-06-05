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
