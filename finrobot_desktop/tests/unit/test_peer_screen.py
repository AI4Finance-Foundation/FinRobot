from finrobot.engine.compute.operators.cyclical_peers import screen_peers_with_cyclical
from finrobot.engine.compute.operators.peer_screen import (
    _normalize_issuer_name,
    screen_peers,
)


def _assert_one_row_per_issuer(result, payload) -> None:
    """Invariant: no two SELECTED peers are the same issuer (same normalized name
    AND market caps within the dedup band). Guards the JPM RY.TO+RY class of
    median-polluting cross-listing / dual-class double-counts."""
    names = payload.get("names") or {}
    quotes = payload["quotes"]
    tol = 3.0
    for i, a in enumerate(result.tickers):
        for b in result.tickers[i + 1 :]:
            na = _normalize_issuer_name(str(names.get(a, "")))
            nb = _normalize_issuer_name(str(names.get(b, "")))
            ma = float(quotes[a]["market_cap"])
            mb = float(quotes[b]["market_cap"])
            near = ma > 0 and mb > 0 and max(ma, mb) / min(ma, mb) <= tol
            assert not (na and na == nb and near), (
                f"{a} and {b} are the same issuer but both selected: {result.tickers}"
            )


def _jpm_bank_payload() -> dict:
    """JPM's bank peer pool with Royal Bank of Canada cross-listed as BOTH RY.TO
    (Toronto) and RY (NYSE) — the 2026-07-02 bug: near-identical market cap, both
    land in the set, and the issuer's P/B (and here its P/E) double-weights the
    peer median. Trailing P/E is chosen so the double-count visibly moves the
    selected median (12.0 polluted vs 11.5 deduped)."""
    return {
        "profile": {
            "company_name": "JPMorgan Chase & Co.",
            "sector": "Financial Services",
            "industry": "Banks - Diversified",
            "market_cap": 700_000_000_000,
            "description": "Global bank holding company.",
        },
        "industry_screen": ["BAC", "RY.TO", "HSBC", "RY", "TD.TO", "WFC", "C"],
        "stock_peers": [],
        "sector_screen": [],
        "quotes": {
            "BAC": {"market_cap": 380_000_000_000, "pe": 12.0},
            "RY.TO": {"market_cap": 288_000_000_000, "pe": 14.0},
            "RY": {"market_cap": 288_000_000_000, "pe": 14.0},
            "HSBC": {"market_cap": 220_000_000_000, "pe": 9.0},
            "TD.TO": {"market_cap": 140_000_000_000, "pe": 11.0},
            "WFC": {"market_cap": 260_000_000_000, "pe": 13.0},
            "C": {"market_cap": 160_000_000_000, "pe": 8.0},
        },
        "names": {
            "BAC": "Bank of America Corporation",
            "RY.TO": "Royal Bank of Canada",
            "RY": "Royal Bank of Canada",
            "HSBC": "HSBC Holdings plc",
            "TD.TO": "The Toronto-Dominion Bank",
            "WFC": "Wells Fargo & Company",
            "C": "Citigroup Inc.",
        },
    }


def test_cross_listed_same_issuer_deduped_to_primary_us_listing() -> None:
    """RY.TO and RY are one issuer (Royal Bank of Canada). Exactly one survives,
    and it is the unsuffixed US listing (RY), not the Toronto ticker (RY.TO)."""
    payload = _jpm_bank_payload()
    result = screen_peers(payload, "JPM")

    assert "RY" in result.tickers
    assert "RY.TO" not in result.tickers
    assert "RY.TO" in result.dropped_duplicate
    # One row per issuer in the selected sheet.
    _assert_one_row_per_issuer(result, payload)
    # The redundant listing no longer double-weights the median: deduped 11.5 vs
    # the polluted 12.0 you get when RY.TO and RY both count.
    assert result.selected_median_pe == 11.5
    # Deterministic.
    assert result == screen_peers(payload, "JPM")


def test_cross_listing_dedup_frees_slot_for_next_peer() -> None:
    """Dropping the duplicate listing frees its top-N slot for the next real peer
    so the comp sheet stays full (dedup thins issuers, not the sheet size)."""
    payload = _jpm_bank_payload()
    # An 8th distinct bank; with RY.TO removed it takes the freed slot (top_n=7).
    payload["industry_screen"].append("USB")
    payload["quotes"]["USB"] = {"market_cap": 70_000_000_000, "pe": 10.0}
    payload["names"]["USB"] = "U.S. Bancorp"

    result = screen_peers(payload, "JPM")

    assert len(result.tickers) == 7  # sheet refilled, not left at 6
    assert "RY.TO" not in result.tickers
    assert "RY" in result.tickers
    assert "USB" in result.tickers  # freed slot went to the next distinct issuer
    _assert_one_row_per_issuer(result, payload)


def test_dual_class_same_issuer_deduped_by_name() -> None:
    """Dual-class listings (GOOGL Class A + GOOG Class C = Alphabet) share no base
    symbol but ARE one issuer — the normalized NAME collapses them so Alphabet
    counts once. Keeps the larger-cap / alphabetically-first class."""
    payload = {
        "profile": {
            "company_name": "Microsoft Corporation",
            "sector": "Technology",
            "industry": "Software - Infrastructure",
            "market_cap": 3_400_000_000_000,
            "description": "Software and cloud.",
        },
        "industry_screen": ["GOOGL", "GOOG", "META", "AMZN"],
        "stock_peers": [],
        "sector_screen": [],
        "quotes": {
            "GOOGL": {"market_cap": 2_300_000_000_000, "pe": 24.0},
            "GOOG": {"market_cap": 2_290_000_000_000, "pe": 24.0},
            "META": {"market_cap": 1_500_000_000_000, "pe": 27.0},
            "AMZN": {"market_cap": 2_400_000_000_000, "pe": 40.0},
        },
        "names": {
            "GOOGL": "Alphabet Inc.",
            "GOOG": "Alphabet Inc.",
            "META": "Meta Platforms, Inc.",
            "AMZN": "Amazon.com, Inc.",
        },
    }

    result = screen_peers(payload, "MSFT")

    assert "GOOGL" in result.tickers
    assert "GOOG" not in result.tickers
    assert "GOOG" in result.dropped_duplicate
    _assert_one_row_per_issuer(result, payload)


def test_distinct_issuers_sharing_a_common_name_word_not_merged() -> None:
    """Control group: the Coca-Cola family (KO / KOF / COKE / CCEP) are DIFFERENT
    issuers that merely share the words 'Coca-Cola'. Conservative name
    normalization keeps their keys distinct, so none is wrongly deduped."""
    payload = {
        "profile": {
            "company_name": "The Coca-Cola Company",
            "sector": "Consumer Defensive",
            "industry": "Beverages - Non-Alcoholic",
            "market_cap": 300_000_000_000,
            "description": "Beverages.",
        },
        "industry_screen": ["PEP", "MNST", "CCEP", "KDP", "KOF", "COKE"],
        "stock_peers": [],
        "sector_screen": [],
        "quotes": {
            "PEP": {"market_cap": 230_000_000_000, "pe": 22.0},
            "MNST": {"market_cap": 55_000_000_000, "pe": 30.0},
            "CCEP": {"market_cap": 40_000_000_000, "pe": 19.0},
            "KDP": {"market_cap": 45_000_000_000, "pe": 18.0},
            "KOF": {"market_cap": 20_000_000_000, "pe": 16.0},
            "COKE": {"market_cap": 12_000_000_000, "pe": 21.0},
        },
        "names": {
            "PEP": "PepsiCo, Inc.",
            "MNST": "Monster Beverage Corporation",
            "CCEP": "Coca-Cola Europacific Partners plc",
            "KDP": "Keurig Dr Pepper Inc.",
            "KOF": "Coca-Cola FEMSA, S.A.B. de C.V.",
            "COKE": "Coca-Cola Consolidated, Inc.",
        },
    }

    result = screen_peers(payload, "KO")

    assert result.dropped_duplicate == []
    assert set(result.tickers) == {"PEP", "MNST", "CCEP", "KDP", "KOF", "COKE"}
    _assert_one_row_per_issuer(result, payload)


def test_same_base_symbol_different_company_not_merged() -> None:
    """Veto: two DIFFERENT companies that happen to share a base ticker across
    exchanges (a US 'ABC' and a London 'ABC.L') must NOT merge — present, differing
    names are authoritative even though the base symbol and market cap coincide."""
    payload = {
        "profile": {
            "company_name": "Target Co",
            "sector": "Industrials",
            "industry": "Specialty Industrial Machinery",
            "market_cap": 100_000_000_000,
            "description": "Industrial.",
        },
        "industry_screen": ["ABC", "ABC.L", "DEF"],
        "stock_peers": [],
        "sector_screen": [],
        "quotes": {
            "ABC": {"market_cap": 50_000_000_000, "pe": 18.0},
            "ABC.L": {"market_cap": 52_000_000_000, "pe": 20.0},
            "DEF": {"market_cap": 40_000_000_000, "pe": 15.0},
        },
        "names": {
            "ABC": "Alpha Industrial Corporation",
            "ABC.L": "Beta Machinery plc",
            "DEF": "Delta Works Inc.",
        },
    }

    result = screen_peers(payload, "TGT")

    assert {"ABC", "ABC.L", "DEF"}.issubset(set(result.tickers))
    assert result.dropped_duplicate == []


def test_target_own_cross_listing_excluded_as_self_comp() -> None:
    """A candidate that is the TARGET under another listing (RY.TO when the target
    is RY) is a self-comp and is dropped as a duplicate, not shipped as a peer."""
    payload = {
        "profile": {
            "company_name": "Royal Bank of Canada",
            "sector": "Financial Services",
            "industry": "Banks - Diversified",
            "market_cap": 288_000_000_000,
            "description": "Canadian bank.",
        },
        "industry_screen": ["RY.TO", "TD", "BNS"],
        "stock_peers": [],
        "sector_screen": [],
        "quotes": {
            "RY.TO": {"market_cap": 288_000_000_000, "pe": 14.0},
            "TD": {"market_cap": 140_000_000_000, "pe": 11.0},
            "BNS": {"market_cap": 90_000_000_000, "pe": 10.0},
        },
        "names": {
            "RY.TO": "Royal Bank of Canada",
            "TD": "The Toronto-Dominion Bank",
            "BNS": "The Bank of Nova Scotia",
        },
    }

    result = screen_peers(payload, "RY")

    assert "RY.TO" not in result.tickers
    assert "RY.TO" in result.dropped_duplicate
    assert {"TD", "BNS"}.issubset(set(result.tickers))


def test_cross_listing_dedup_falls_back_to_base_symbol_without_names() -> None:
    """A stale payload without the ``names`` map still dedups a shared-base-symbol
    cross-listing (RY.TO + RY) via the base-symbol fallback + market-cap band."""
    payload = _jpm_bank_payload()
    del payload["names"]  # simulate a pre-``names`` cached payload
    result = screen_peers(payload, "JPM")

    assert "RY" in result.tickers
    assert "RY.TO" not in result.tickers
    assert "RY.TO" in result.dropped_duplicate


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


def _mu_payload() -> dict:
    """MU's REAL candidate shape (live-verified 2026-06-14): the storage cohort
    (WDC/STX/SNDK) sits only in sector_screen; industry_screen + stock_peers are
    all logic semis / equipment. STX is a pure HDD maker — its description carries
    NO semiconductor token, so the role gate would reject it. WDC ($182B) loses the
    size-proximity race to the giant logic semis. Both must survive via protection.
    """
    return {
        "profile": {
            "company_name": "Micron Technology, Inc.",
            "sector": "Technology",
            "industry": "Semiconductors",
            "market_cap": 1_100_000_000_000,
            "description": "Develops, manufactures, and sells semiconductor memory and storage.",
        },
        "industry_screen": ["NVDA", "AVGO", "AMD", "ARM", "TXN"],  # giant logic semis
        "stock_peers": ["AMAT", "KLAC", "LRCX"],
        "sector_screen": ["WDC", "STX", "SNDK"],  # storage cohort hides here (Tier 3)
        "quotes": {
            "NVDA": {"market_cap": 4_953_000_000_000, "pe": 31.2},
            "AVGO": {"market_cap": 1_817_000_000_000, "pe": 61.9},
            "AMD": {"market_cap": 845_000_000_000, "pe": 166.6},
            "ARM": {"market_cap": 405_000_000_000, "pe": 447.8},
            "TXN": {"market_cap": 274_000_000_000, "pe": 51.0},
            "AMAT": {"market_cap": 450_000_000_000, "pe": 52.9},
            "KLAC": {"market_cap": 332_000_000_000, "pe": 71.3},
            "LRCX": {"market_cap": 458_000_000_000, "pe": 68.3},
            "WDC": {"market_cap": 182_000_000_000, "pe": 29.9},
            "STX": {"market_cap": 208_000_000_000, "pe": 86.5},
            "SNDK": {"market_cap": 278_000_000_000, "pe": 65.0},
        },
        "profiles": {
            "NVDA": {"description": "Designs GPUs and data center platforms."},
            "AVGO": {"description": "Designs and supplies semiconductor solutions."},
            "AMD": {"description": "Designs microprocessors and GPUs."},
            "ARM": {"description": "Designs and licenses processor chip architectures."},
            "TXN": {"description": "Designs and manufactures analog semiconductor chips."},
            "AMAT": {"description": "Semiconductor equipment systems; deposition and etch."},
            "KLAC": {"description": "Semiconductor inspection systems and metrology."},
            "LRCX": {"description": "Semiconductor wafer processing equipment; etch."},
            # WDC carries "wafer" → role design; STX is pure HDD (no semi token → role None);
            # both must survive ANYWAY because they are protected cohort members.
            "WDC": {
                "description": "Designs and markets data storage devices; flash memory wafers."
            },
            "STX": {"description": "Global provider of data storage technology; hard disk drives."},
            "SNDK": {"description": "Designs and supplies NAND flash storage and wafers."},
        },
    }


def test_mu_storage_cohort_survives_role_gate_and_size_race() -> None:
    """Regression钉死 for the MU comps bug (2026-06-14): the curated storage cohort
    (WDC/STX/SNDK) must end up in MU's peer set — WDC/STX must NOT be evicted by the
    giant logic semis winning the intra-tier size-proximity race, and STX must NOT be
    role-dropped just because Seagate's description carries no semiconductor token.
    """
    result = screen_peers_with_cyclical(_mu_payload(), "MU")
    # The full hand-curated storage cohort is present.
    assert {"WDC", "STX", "SNDK"}.issubset(set(result.tickers))
    # STX would be role-dropped without protection (no semiconductor token) — assert
    # protection overrode the gate: it is selected, not in dropped_role.
    assert "STX" not in result.dropped_role
    assert "STX" in result.tickers
    # The sheet is not stacked entirely with growth-stock logic semis.
    logic_semis = {"NVDA", "AVGO", "AMD", "ARM", "TXN"} & set(result.tickers)
    assert len(logic_semis) <= 4  # at least 3 of 7 slots go to the storage cohort
    # Deterministic.
    assert result == screen_peers_with_cyclical(_mu_payload(), "MU")


def test_mu_protection_does_not_pin_a_member_lacking_a_quote() -> None:
    """Protection asserts "this is a genuine comp", not "ship it blind": a cohort
    member with no provider quote is still dropped (fail-safe to existing behaviour)."""
    payload = _mu_payload()
    del payload["quotes"]["STX"]  # provider omitted STX's quote
    result = screen_peers_with_cyclical(payload, "MU")
    assert "STX" not in result.tickers
    # WDC/SNDK (quoted) still survive.
    assert {"WDC", "SNDK"}.issubset(set(result.tickers))


def test_foundry_target_excludes_idm_keeps_pure_play() -> None:
    """Regression钉死 for the TSM comps bug (2026-06-14): a foundry target's peer set
    must keep only pure-play contract foundries (UMC/GFS/TSEM) and exclude IDMs
    (NXPI/MCHP/ON/QRVO) that the over-broad foundry classifier used to misclassify.
    """
    payload = {
        "profile": {
            "company_name": "Taiwan Semiconductor Manufacturing Company Limited",
            "sector": "Technology",
            "industry": "Semiconductors",
            "market_cap": 2_198_000_000_000,
            "description": (
                "TSMC specializes in the manufacturing, packaging, and testing of integrated "
                "circuits; renowned for its wafer fabrication processes and core foundry services."
            ),
        },
        "industry_screen": ["UMC", "GFS", "TSEM", "NXPI", "MCHP", "ON", "QRVO"],
        "stock_peers": [],
        "sector_screen": [],
        # All mcaps clear TSM's 1/200x floor ($11B) and stay under the 20x ceiling,
        # so the ONLY discriminator under test is the value-chain role gate.
        "quotes": {
            "UMC": {"market_cap": 54_000_000_000, "pe": 33.3},
            "GFS": {"market_cap": 45_000_000_000, "pe": 58.1},
            "TSEM": {"market_cap": 18_000_000_000, "pe": 30.0},
            "NXPI": {"market_cap": 77_000_000_000, "pe": 29.0},
            "MCHP": {"market_cap": 50_000_000_000, "pe": 255.1},
            "ON": {"market_cap": 45_000_000_000, "pe": 80.2},
            "QRVO": {"market_cap": 30_000_000_000, "pe": 40.0},
        },
        "profiles": {
            "UMC": {"description": "Operates as a specialized semiconductor wafer foundry."},
            "GFS": {"description": "Operates as a prominent global semiconductor foundry."},
            "TSEM": {"description": "Operates as an independent semiconductor foundry."},
            "NXPI": {
                "description": (
                    "Specializes in the design and production of semiconductor solutions; "
                    "serves OEMs, contract manufacturers, and distributors."
                )
            },
            "MCHP": {
                "description": (
                    "Creates, produces, and sells embedded control solutions; delivers wafer "
                    "foundry, assembly, and test subcontracting manufacturing services."
                )
            },
            "ON": {
                "description": (
                    "Global provider of power and sensing solutions; designs and develops "
                    "analog products; provides foundry and design services for government clients."
                )
            },
            "QRVO": {
                "description": (
                    "Global technology company focused on developing and bringing to market RF "
                    "products; supplies specialized compound semiconductor foundry services."
                )
            },
        },
    }

    result = screen_peers(payload, "TSM")

    assert set(result.tickers) == {"UMC", "GFS", "TSEM"}
    for idm in ("NXPI", "MCHP", "ON", "QRVO"):
        assert idm not in result.tickers
        assert idm in result.dropped_role
    assert result == screen_peers(payload, "TSM")


def test_foundry_target_excludes_fab_tool_equipment_vendor() -> None:
    """Regression钉死 for the TSM/AMAT bug (2026-07-02): Applied Materials makes the
    TOOLS used to fabricate chips (equipment), not chips — but its real FMP
    description ("materials engineering solutions … critical wafer fabrication tools")
    misses the narrow equipment vocabulary while greedily matching the foundry
    substring "wafer fabrication", so it was mis-tagged foundry and drove TSM's comps.
    """
    payload = {
        "profile": {
            "company_name": "Taiwan Semiconductor Manufacturing Company Limited",
            "sector": "Technology",
            "industry": "Semiconductors",
            "market_cap": 2_198_000_000_000,
            "description": (
                "TSMC specializes in the manufacturing, packaging, and testing of integrated "
                "circuits; renowned for its wafer fabrication processes and core foundry services."
            ),
        },
        "industry_screen": ["UMC", "GFS", "TSEM", "AMAT"],
        "stock_peers": [],
        "sector_screen": [],
        "quotes": {
            "UMC": {"market_cap": 54_000_000_000, "pe": 33.3},
            "GFS": {"market_cap": 45_000_000_000, "pe": 58.1},
            "TSEM": {"market_cap": 18_000_000_000, "pe": 30.0},
            "AMAT": {"market_cap": 180_000_000_000, "pe": 25.0},
        },
        "profiles": {
            "UMC": {"description": "Operates as a specialized semiconductor wafer foundry."},
            "GFS": {"description": "Operates as a prominent global semiconductor foundry."},
            "TSEM": {"description": "Operates as an independent semiconductor foundry."},
            "AMAT": {
                "description": (
                    "Applied Materials, Inc. engages in provision of materials engineering "
                    "solutions used to produce semiconductors. The firm also focuses on design, "
                    "development, production, and servicing of the critical wafer fabrication "
                    "tools used for customers to manufacture semiconductors."
                )
            },
        },
    }

    result = screen_peers(payload, "TSM")

    assert set(result.tickers) == {"UMC", "GFS", "TSEM"}
    assert "AMAT" not in result.tickers
    assert "AMAT" in result.dropped_role


def test_preferred_stock_listing_excluded_from_peer_set() -> None:
    """Regression钉死 for the C/MER-PK bug (2026-07-02): a preferred listing (FMP
    ``MER-PK``) trades near par, carries the parent's cap/financials, and its bank
    net-revenue caliber collapses to non-positive — which crashed the WHOLE peer set.
    It must be dropped at the screen (not selected), leaving the freed slot for a real
    common-stock peer. Common dual-class (BRK-B) must NOT be swept up.
    """
    payload = {
        "profile": {
            "company_name": "Citigroup Inc.",
            "sector": "Financial Services",
            "industry": "Banks - Diversified",
            "market_cap": 239_000_000_000,
        },
        "industry_screen": ["WFC", "MER-PK", "MUFG", "TD", "BRK-B", "BAC"],
        "stock_peers": [],
        "sector_screen": [],
        "names": {
            "WFC": "Wells Fargo & Company",
            "MER-PK": "Merrill Lynch & Co., Inc.",  # name carries NO "preferred" token
            "MUFG": "Mitsubishi UFJ Financial Group, Inc.",
            "TD": "The Toronto-Dominion Bank",
            "BRK-B": "Berkshire Hathaway Inc.",
            "BAC": "Bank of America Corporation",
        },
        "quotes": {
            "WFC": {"market_cap": 260_000_000_000, "pe": 14.0},
            "MER-PK": {"market_cap": 194_000_000_000, "pe": 6.4},  # parent-attributed cap/pe
            "MUFG": {"market_cap": 200_000_000_000, "pe": 12.0},
            "TD": {"market_cap": 130_000_000_000, "pe": 13.0},
            "BRK-B": {"market_cap": 900_000_000_000, "pe": 10.0},
            "BAC": {"market_cap": 320_000_000_000, "pe": 13.5},
        },
    }

    result = screen_peers(payload, "C")

    assert "MER-PK" not in result.tickers
    assert "MER-PK" in result.dropped_non_common
    # A common dual-class listing is a real comp — never swept up as "non-common".
    assert "BRK-B" not in result.dropped_non_common
    assert {"WFC", "MUFG", "TD", "BAC"}.issubset(set(result.tickers))


def test_bare_symbol_preferred_baby_bonds_excluded_from_peer_set() -> None:
    """Regression钉死 for the insurer preferred-median bug (2026-07-06): FMP lists
    Aegon / Athene preferreds & baby-bonds under BARE symbols (AEB/AED/AEH/ATHS, no
    ``-P`` marker) named after the parent plus an instrument descriptor. They fetch the
    parent's balance sheet against a ~$25-par price → a garbage ~6x P/B that dragged the
    HIG / AIG insurer P/B median to 2-4x true value. The ``-P`` ticker regex misses them;
    the name-token / coupon-rate backstop must drop them — while the ACTUAL Aegon common
    (AEG "Aegon Ltd.") and real insurer commons are kept.
    """
    payload = {
        "profile": {
            "company_name": "American International Group, Inc.",
            "sector": "Financial Services",
            "industry": "Insurance - Diversified",
            "market_cap": 42_000_000_000,
        },
        "industry_screen": ["ACGL", "AEB", "AED", "AEH", "ATHS", "AEG", "HIG", "SLF"],
        "stock_peers": [],
        "sector_screen": [],
        "names": {
            "ACGL": "Arch Capital Group Ltd.",  # 'Capital' must NOT trip 'CAP SEC'
            "AEB": "Aegon N.V. PERP CAP FLTG RT",
            "AED": "Aegon N.V. PERP CAP SECS",
            "AEH": "Aegon N.V. PRP CP SEC 6.375",
            "ATHS": "Athene Holding Ltd. 7.250% Fixe",  # coupon-rate signature
            "AEG": "Aegon Ltd.",  # the ACTUAL common — must survive
            "HIG": "The Hartford Financial Services Group",
            "SLF": "Sun Life Financial Inc.",
        },
        "quotes": {
            "ACGL": {"market_cap": 34_000_000_000, "pe": 11.0},
            "AEB": {"market_cap": 51_000_000_000, "pe": 8.0},  # parent-attributed cap
            "AED": {"market_cap": 52_000_000_000, "pe": 8.0},
            "AEH": {"market_cap": 52_000_000_000, "pe": 8.0},
            "ATHS": {"market_cap": 19_000_000_000, "pe": 9.0},
            "AEG": {"market_cap": 13_000_000_000, "pe": 7.0},
            "HIG": {"market_cap": 38_000_000_000, "pe": 11.0},
            "SLF": {"market_cap": 40_000_000_000, "pe": 12.0},
        },
    }

    result = screen_peers(payload, "AIG")

    for pref in ("AEB", "AED", "AEH", "ATHS"):
        assert pref not in result.tickers, f"{pref} preferred leaked into peer set"
        assert pref in result.dropped_non_common, f"{pref} not recorded as non-common"
    # The actual Aegon common and real insurer commons are kept.
    assert "AEG" not in result.dropped_non_common
    assert {"ACGL", "AEG", "HIG", "SLF"}.issubset(set(result.tickers))


# ── Liveness (delisted / renamed) gate ────────────────────────────────────────
# Field structure (quotes / names / the new ``active`` bool map) and the market caps
# / names / isActivelyTrading values for VMW, SQ, XYZ are taken from the live FMP
# /profile + /company-screener pull on 2026-07-07 (VMW isActivelyTrading=False, frozen
# ~$61.5B cap; SQ isActivelyTrading=False, stale ~$51.7B; XYZ isActivelyTrading=True,
# live ~$47.0B — SQ and XYZ both name "Block, Inc."). P/E values are round test
# scaffolding (the liveness gate acts before the P/E gate), never copied from code.


def test_delisted_candidate_dropped_and_recorded() -> None:
    """A candidate the provider flags isActivelyTrading=False (VMware VMW, absorbed into
    Broadcom in 2023 — frozen at $142.48 with a stale ~$61.5B cap) is not a live trading
    comp: it is dropped, recorded in ``dropped_delisted``, and named in the auditable
    rationale. It must not be mis-filed under another drop bucket."""
    payload = {
        "profile": {
            "company_name": "Microsoft Corporation",
            "sector": "Technology",
            "industry": "Software - Infrastructure",
            "market_cap": 3_000_000_000_000,
            "description": "Cloud software and productivity services.",
        },
        "industry_screen": ["CRM", "ORCL", "VMW", "NOW"],
        "stock_peers": [],
        "sector_screen": [],
        "quotes": {
            "CRM": {"market_cap": 250_000_000_000, "pe": 40.0},
            "ORCL": {"market_cap": 400_000_000_000, "pe": 30.0},
            "VMW": {"market_cap": 61_521_441_480, "pe": 20.0},  # stale frozen cap
            "NOW": {"market_cap": 190_000_000_000, "pe": 55.0},
        },
        "names": {
            "CRM": "Salesforce, Inc.",
            "ORCL": "Oracle Corporation",
            "VMW": "VMware, Inc.",
            "NOW": "ServiceNow, Inc.",
        },
        "active": {"CRM": True, "ORCL": True, "VMW": False, "NOW": True},
    }

    result = screen_peers(payload, "MSFT")

    assert "VMW" not in result.tickers
    assert "VMW" in result.dropped_delisted
    # Not mis-attributed to another drop bucket.
    assert "VMW" not in result.dropped_duplicate
    assert "VMW" not in result.dropped_role
    assert "VMW" not in result.dropped_nm
    # The live peers are kept.
    assert {"CRM", "ORCL", "NOW"}.issubset(set(result.tickers))
    # Auditable: the delisted drop is named in the rationale trace.
    assert "delisted/renamed" in result.rationale
    assert "VMW" in result.rationale
    # Deterministic.
    assert result == screen_peers(payload, "MSFT")


def test_same_issuer_keeps_live_listing_over_delisted_ticker() -> None:
    """Old Block ``SQ`` (renamed to ``XYZ`` in 2025) and the live ``XYZ`` are ONE issuer
    ("Block, Inc.") — same normalized name, market caps within the dedup band. The dead SQ
    even carries the LARGER (stale, frozen) cap, so the ``-cap`` tiebreak alone would keep
    SQ and drop the live XYZ (the pre-fix bug). The liveness key in ``_keep_rank`` makes the
    LIVE listing win the same-issuer dedup."""
    payload = {
        "profile": {
            "company_name": "Microsoft Corporation",
            "sector": "Technology",
            "industry": "Software - Infrastructure",
            "market_cap": 3_000_000_000_000,
            "description": "Cloud software and productivity services.",
        },
        "industry_screen": ["SQ", "XYZ", "CRM", "ORCL"],
        "stock_peers": [],
        "sector_screen": [],
        "quotes": {
            "SQ": {"market_cap": 51_729_675_689, "pe": 18.0},  # dead, stale LARGER cap
            "XYZ": {"market_cap": 46_977_637_514, "pe": 18.0},  # live, smaller cap
            "CRM": {"market_cap": 250_000_000_000, "pe": 40.0},
            "ORCL": {"market_cap": 400_000_000_000, "pe": 30.0},
        },
        "names": {
            "SQ": "Block, Inc.",
            "XYZ": "Block, Inc.",
            "CRM": "Salesforce, Inc.",
            "ORCL": "Oracle Corporation",
        },
        "active": {"SQ": False, "XYZ": True, "CRM": True, "ORCL": True},
    }

    result = screen_peers(payload, "MSFT")

    # The live listing is kept; the dead one is deduped out to the live issuer.
    assert "XYZ" in result.tickers
    assert "SQ" not in result.tickers
    assert "SQ" in result.dropped_duplicate
    # One row per issuer — Block counted exactly once.
    _assert_one_row_per_issuer(result, payload)

    # Control: WITHOUT the liveness signal the stale, larger-cap dead SQ wins the -cap
    # tiebreak (the pre-fix behaviour), keeping the delisted ticker and dropping the live one.
    stale_payload = {k: v for k, v in payload.items() if k != "active"}
    stale = screen_peers(stale_payload, "MSFT")
    assert "SQ" in stale.tickers
    assert "XYZ" not in stale.tickers


def test_protected_cohort_member_flagged_inactive_is_kept_and_disclosed() -> None:
    """A curated/protected cohort member (MU's storage peer STX) that the provider flags
    inactive is KEPT by the curation override — the override must beat every downstream gate
    (the 2026-06-14 MU lesson) — and the override is DISCLOSED in the rationale, not silently
    applied. A kept-by-override member must NOT appear in ``dropped_delisted``."""
    payload = _mu_payload()
    # Provider (hypothetically) flags Seagate inactive; the rest live.
    payload["active"] = {
        "WDC": True,
        "STX": False,
        "SNDK": True,
        "NVDA": True,
        "AVGO": True,
        "AMD": True,
        "ARM": True,
        "TXN": True,
        "AMAT": True,
        "KLAC": True,
        "LRCX": True,
    }

    result = screen_peers_with_cyclical(payload, "MU")

    # Kept despite the inactive flag (curation override), and NOT recorded as delisted.
    assert "STX" in result.tickers
    assert "STX" not in result.dropped_delisted
    # The override is disclosed in the rationale, naming STX.
    assert "curation override" in result.rationale
    assert "STX" in result.rationale
    # The other curated members are unaffected.
    assert {"WDC", "SNDK"}.issubset(set(result.tickers))


def test_missing_active_key_never_drops_a_candidate_for_liveness() -> None:
    """Back-compat: a stale pre-``active`` cached payload (no ``active`` key at all) has NO
    liveness signal, so every candidate reads as UNKNOWN and NONE is dropped for liveness —
    identical to the pre-gate behaviour. A delisted VMW here is NOT dropped, because there is
    no signal that it is dead (exactly as the screen behaved before the liveness gate)."""
    payload = {
        "profile": {
            "company_name": "Microsoft Corporation",
            "sector": "Technology",
            "industry": "Software - Infrastructure",
            "market_cap": 3_000_000_000_000,
            "description": "Cloud software and productivity services.",
        },
        "industry_screen": ["CRM", "ORCL", "VMW"],
        "stock_peers": [],
        "sector_screen": [],
        "quotes": {
            "CRM": {"market_cap": 250_000_000_000, "pe": 40.0},
            "ORCL": {"market_cap": 400_000_000_000, "pe": 30.0},
            "VMW": {"market_cap": 61_521_441_480, "pe": 20.0},
        },
        "names": {
            "CRM": "Salesforce, Inc.",
            "ORCL": "Oracle Corporation",
            "VMW": "VMware, Inc.",
        },
        # NB: no "active" key — a pre-change cached payload.
    }

    result = screen_peers(payload, "MSFT")

    assert result.dropped_delisted == []
    # Unknown liveness never mis-kills — VMW stays in (pre-gate behaviour).
    assert set(result.tickers) == {"CRM", "ORCL", "VMW"}


def test_candidate_absent_from_active_map_is_unknown_not_dropped() -> None:
    """UNKNOWN (a present ``active`` map that simply omits this candidate — e.g. a
    stock-peers-only name whose /profile backfill failed) is not the same as dead: only an
    EXPLICIT False drops. VMW here is absent from the map, so it is kept."""
    payload = {
        "profile": {
            "company_name": "Microsoft Corporation",
            "sector": "Technology",
            "industry": "Software - Infrastructure",
            "market_cap": 3_000_000_000_000,
            "description": "Cloud software and productivity services.",
        },
        "industry_screen": ["CRM", "ORCL", "VMW"],
        "stock_peers": [],
        "sector_screen": [],
        "quotes": {
            "CRM": {"market_cap": 250_000_000_000, "pe": 40.0},
            "ORCL": {"market_cap": 400_000_000_000, "pe": 30.0},
            "VMW": {"market_cap": 61_521_441_480, "pe": 20.0},
        },
        "names": {
            "CRM": "Salesforce, Inc.",
            "ORCL": "Oracle Corporation",
            "VMW": "VMware, Inc.",
        },
        # VMW deliberately absent from the map (unknown); CRM/ORCL known live.
        "active": {"CRM": True, "ORCL": True},
    }

    result = screen_peers(payload, "MSFT")

    assert result.dropped_delisted == []
    assert "VMW" in result.tickers


# ── Mega-cap tier fix: size-gap demotion of far high-affinity candidates ──────
# (2026-07-07, lead-signed G=5.) Shapes modeled on the LIVE MSFT peer_candidates
# payload (target $2.87T; Software-Infrastructure Tier 1 all 6.9–90x smaller;
# FMP stock_peers cross-recommending the ~1.5x mega-caps) — the regime where
# same-tier size proximity anchored the comps median on PLTR/PANW-class
# mid-caps while AAPL/GOOGL/NVDA never got a slot.


def _megacap_software_payload() -> dict:
    return {
        "profile": {
            "company_name": "Bigsoft Corporation",
            "sector": "Technology",
            "industry": "Software - Infrastructure",
            "market_cap": 2_870_000_000_000,
            "description": "Cloud software and productivity services.",
        },
        # Tier 1: same industry, ALL beyond the 5x gap (6.9x … 34x).
        "industry_screen": ["ORC", "PLT", "PAN", "FTN", "SNP"],
        # Tier 2: cross-recommendations — three ~1.5x mega-caps + one far (24x).
        "stock_peers": ["MEGA1", "MEGA2", "MEGA3", "FTN"],
        "sector_screen": [],
        "quotes": {
            "ORC": {"market_cap": 414_000_000_000, "pe": 24.2},
            "PLT": {"market_cap": 304_000_000_000, "pe": 138.1},
            "PAN": {"market_cap": 243_000_000_000, "pe": 300.4},
            "FTN": {"market_cap": 119_000_000_000, "pe": 62.4},
            "SNP": {"market_cap": 85_000_000_000, "pe": 100.1},
            "MEGA1": {"market_cap": 4_590_000_000_000, "pe": 37.7},
            "MEGA2": {"market_cap": 4_430_000_000_000, "pe": 27.7},
            "MEGA3": {"market_cap": 4_740_000_000_000, "pe": 29.8},
        },
        "names": {
            "ORC": "Oracle-like Corp",
            "PLT": "Palantir-like Inc",
            "PAN": "Firewall-like Inc",
            "FTN": "Fortinet-like Inc",
            "SNP": "Synopsys-like Inc",
            "MEGA1": "Fruit Devices Inc",
            "MEGA2": "Search Giant Inc",
            "MEGA3": "GPU Giant Inc",
        },
    }


def test_megacap_target_demotes_far_industry_tier_behind_cross_recommended_megacaps() -> None:
    """The 2026-07-07 MSFT regime: every Tier-1 name is >5x smaller, the true
    ~1.5x peers sit in Tier 2. The near Tier-2 mega-caps must lead the set, and
    the demoted far pool must refill by GLOBAL size proximity (ORC 6.9x before
    FTN 24x, regardless of FTN's Tier-2 label)."""
    result = screen_peers(_megacap_software_payload(), "BIGS", top_n=7)

    # Near mega-caps first (Tier-2, within the gap), by size proximity.
    assert result.tickers[:3] == ["MEGA2", "MEGA1", "MEGA3"]
    # Far pool refills globally by proximity: ORC (6.9x) … SNP (34x); FTN's
    # Tier-2 membership gives it no priority once it is beyond the gap.
    assert result.tickers[3:] == ["ORC", "PLT", "PAN", "FTN"]
    # tier_of keeps the ORIGIN tier label (a demoted T1 pick is still T1).
    assert result.tier_of["MEGA1"] == 2
    assert result.tier_of["ORC"] == 1
    assert result.tier_of["FTN"] == 1  # first-seen tier: industry list
    # The audit trail must say who was demoted and mark far picks.
    assert "demoted behind the near tiers" in result.rationale
    assert "ORC(T1→far" in result.rationale


def test_size_adjacent_tier_unchanged_by_demotion() -> None:
    """A small/mid-cap whose Tier 1 is size-adjacent (all within 5x) must select
    byte-identically with the demotion rule on or off — the mega-cap fix must
    not touch the common case."""
    payload = {
        "profile": {
            "company_name": "Midcap Widgets Inc",
            "sector": "Industrials",
            "industry": "Widgets",
            "market_cap": 20_000_000_000,
            "description": "Widget maker.",
        },
        "industry_screen": ["WID1", "WID2", "WID3"],
        "stock_peers": ["WID4"],
        "sector_screen": [],
        "quotes": {
            "WID1": {"market_cap": 30_000_000_000, "pe": 18.0},
            "WID2": {"market_cap": 12_000_000_000, "pe": 15.0},
            "WID3": {"market_cap": 55_000_000_000, "pe": 22.0},
            "WID4": {"market_cap": 21_000_000_000, "pe": 17.0},
        },
        "names": {
            "WID1": "Widget One",
            "WID2": "Widget Two",
            "WID3": "Widget Three",
            "WID4": "Widget Four",
        },
    }
    with_demotion = screen_peers(payload, "MIDW")
    without = screen_peers(payload, "MIDW", size_gap_demote=float("inf"))
    # Tier order preserved exactly: T1 by size proximity, then the T2 name.
    assert with_demotion.tickers == without.tickers == ["WID1", "WID2", "WID3", "WID4"]
    assert "demoted" not in with_demotion.rationale


def test_protected_cohort_member_beyond_gap_is_never_demoted() -> None:
    """A curated/protected member sits >5x from the target (WDC/STX vs MU) and is
    exactly what the curation exists to keep: it must stay PINNED at the front of
    Tier 1, not fall into the far pool — while an unprotected name at the same
    gap does demote."""
    payload = {
        "profile": {
            "company_name": "Memory Giant Inc",
            "sector": "Technology",
            "industry": "Semiconductors",
            "market_cap": 1_100_000_000_000,
            "description": "Memory and storage semiconductors.",
        },
        # STOR = curated storage comp at 5.6x (would demote without protection);
        # LOGIC1/LOGIC2 = near logic semis; FARL = unprotected 5.6x name.
        "industry_screen": ["STOR", "LOGIC1", "LOGIC2", "FARL"],
        "stock_peers": [],
        "sector_screen": [],
        "quotes": {
            "STOR": {"market_cap": 196_000_000_000, "pe": 31.0},
            "LOGIC1": {"market_cap": 900_000_000_000, "pe": 179.0},
            "LOGIC2": {"market_cap": 1_780_000_000_000, "pe": 60.0},
            "FARL": {"market_cap": 196_000_000_000, "pe": 25.0},
        },
        "names": {
            "STOR": "Storage Maker Inc",
            "LOGIC1": "Logic Semi One",
            "LOGIC2": "Logic Semi Two",
            "FARL": "Far Logic Inc",
        },
        # Logic-semi candidates carry design-role profiles (the live MU payload
        # ships profiles for a semiconductor target, so the role gate has text to
        # read). STOR deliberately has NO profile — a pure storage maker's
        # description carries no semiconductor token, so the role gate would
        # reject it; protection overrides, mirroring the production MU/WDC/STX path.
        "profiles": {
            "LOGIC1": {
                "company_name": "Logic Semi One",
                "description": "designs and sells logic semiconductor chips",
            },
            "LOGIC2": {
                "company_name": "Logic Semi Two",
                "description": "designs and sells logic semiconductor chips",
            },
            "FARL": {
                "company_name": "Far Logic Inc",
                "description": "designs and sells logic semiconductor chips",
            },
        },
    }
    result = screen_peers(payload, "MEMG", protected_peers=frozenset({"STOR"}), top_n=4)

    # Protected member pinned FIRST despite its 5.6x gap; near names follow by
    # proximity; the unprotected same-gap name comes last via the far pool.
    assert result.tickers == ["STOR", "LOGIC1", "LOGIC2", "FARL"]
    assert "STOR(T1," in result.rationale  # pinned near — NOT marked →far
    assert "FARL(T1→far" in result.rationale


def test_sector_tier_is_not_gap_filtered() -> None:
    """The demotion rule applies to the high-affinity tiers only. A sector-tier
    candidate at 8x (inside the strict 20x band) must still be selectable when
    the sector tier is enabled (thin high-affinity pool)."""
    payload = {
        "profile": {
            "company_name": "Lonely Leader Inc",
            "sector": "Industrials",
            "industry": "Niche Machines",
            "market_cap": 100_000_000_000,
            "description": "Niche machine maker.",
        },
        "industry_screen": ["NICHE1"],
        "stock_peers": [],
        "sector_screen": ["SECT1", "SECT2"],
        "quotes": {
            "NICHE1": {"market_cap": 40_000_000_000, "pe": 14.0},
            "SECT1": {"market_cap": 12_500_000_000, "pe": 16.0},  # 8x — beyond G, in band
            "SECT2": {"market_cap": 90_000_000_000, "pe": 19.0},
        },
        "names": {
            "NICHE1": "Niche One",
            "SECT1": "Sector Eight X",
            "SECT2": "Sector Near",
        },
    }
    result = screen_peers(payload, "LONE")

    # High-affinity pool is 1 (<3) → sector enabled; the 8x sector name is kept.
    assert "SECT1" in result.tickers
    assert result.tier_of["SECT1"] == 3
