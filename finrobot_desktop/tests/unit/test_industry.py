"""Tests for primitives/industry.py — bank classification + net-revenue caliber.

``bank_net_revenue`` expected values are anchored to external truth (SEC XBRL,
JPM FY-Q1 2026 ending 2026-03-31, verified 2026-06-08):
  net interest income (us-gaap:InterestIncomeExpenseNet)    = 25.366B
  noninterest income  (us-gaap:NoninterestIncome)           = 24.470B
  total net revenue   (us-gaap:RevenuesNetOfInterestExpense)= 49.836B  (= NII + noninterest)
FMP serves gross revenue 73.661B and interestExpense 23.825B for that quarter;
73.661B − 23.825B = 49.836B ties to SEC to the penny.
"""

from finrobot.engine.primitives.industry import (
    bank_net_revenue,
    bank_operating_income_net_caliber,
    commodity_cyclical_basis,
    is_balance_sheet_financial,
    is_bank,
    is_commodity_cyclical,
    is_non_life_insurer,
    semiconductor_role,
)


class TestIsBank:
    def test_bank_by_industry(self) -> None:
        assert is_bank(industry="Banks—Diversified") is True
        assert is_bank(industry="Banks—Regional") is True
        assert is_bank(industry="Banks") is True
        assert is_bank(industry="Banks - Diversified") is True

    def test_bank_by_sector_and_industry(self) -> None:
        assert is_bank(industry="Investment Banking", sector="Financial Services") is True
        assert is_bank(industry="Community Banking", sector="Financials") is True

    def test_not_bank(self) -> None:
        assert is_bank(industry="Software") is False
        assert is_bank(industry="Insurance", sector="Financial Services") is False
        assert is_bank(industry=None, sector=None) is False
        assert is_bank(industry="Technology", sector="Technology") is False

    def test_financial_sector_without_bank_keyword(self) -> None:
        """Financial Services sector but industry without 'bank' -> not a bank."""
        assert is_bank(industry="Insurance", sector="Financial Services") is False
        assert is_bank(industry="Asset Management", sector="Financial Services") is False


class TestIsBalanceSheetFinancial:
    """The WIDER cash-flow-suppression predicate (banks + risk-carrying insurers),
    deliberately distinct from is_bank (banks only). An insurer is a DCF category
    error like a bank (is_bank=False but is_balance_sheet_financial=True); an
    insurance BROKER is asset-light with a meaningful EV (False). Single authority
    shared by audit/sector_sign + the valuation aggregator (the ALL BUY+460% fix,
    2026-06-24)."""

    def test_banks_true(self) -> None:
        assert is_balance_sheet_financial("Banks—Diversified") is True
        assert is_balance_sheet_financial("Banks - Regional") is True

    def test_risk_carrying_insurers_true(self) -> None:
        # Load-bearing: insurers carry float/reserves (no clean EBITDA) — a DCF
        # category error is_bank missed, so a P&C insurer anchored a garbage DCF
        # (ALL BUY+460%, 2026-06-24). is_balance_sheet_financial catches them...
        assert is_balance_sheet_financial("Insurance—Property & Casualty") is True
        assert is_balance_sheet_financial("Insurance - Life") is True
        assert is_balance_sheet_financial("Insurance—Diversified") is True
        # ...while is_bank deliberately does NOT (the two predicates differ here).
        assert (
            is_bank(industry="Insurance—Property & Casualty", sector="Financial Services") is False
        )

    def test_insurance_brokers_false(self) -> None:
        # Asset-light fee businesses (AON/MMC/AJG/BRO/WTW) — meaningful EV, not suppressed.
        assert is_balance_sheet_financial("Insurance Brokers") is False
        assert is_balance_sheet_financial("Insurance - Brokers") is False

    def test_asset_light_financials_false(self) -> None:
        # EV is meaningful for these (V/MA, BLK, ICE/CME, GS/MS lumped with boutiques) —
        # must NOT suppress the cash-flow methods.
        assert is_balance_sheet_financial("Asset Management") is False
        assert is_balance_sheet_financial("Financial - Credit Services") is False
        assert is_balance_sheet_financial("Financial - Capital Markets") is False
        assert is_balance_sheet_financial("Financial Data & Stock Exchanges") is False

    def test_non_financial_and_none_false(self) -> None:
        assert is_balance_sheet_financial("Software") is False
        assert is_balance_sheet_financial(None) is False
        assert is_balance_sheet_financial("") is False


class TestIsNonLifeInsurer:
    """The DDM-degradation cohort (2026-07-06): a non-life insurer's underwriting-
    cycle ROE + buyback-driven low payout blow its DDM to multiples of price even at
    through-cycle ROE, so the standalone DDM degrades to relative valuation. Life
    insurers (stable spread, high steady payout) keep the DDM; banks reach DDM via the
    report path and must be untouched here."""

    def test_non_life_insurers_true(self) -> None:
        # P&C (ALL/TRV/CB/PGR), diversified (HIG/AIG), reinsurance, specialty.
        assert is_non_life_insurer("Insurance - Property & Casualty") is True
        assert is_non_life_insurer("Insurance—Diversified") is True
        assert is_non_life_insurer("Insurance - Reinsurance") is True
        assert is_non_life_insurer("Insurance - Specialty") is True

    def test_life_insurers_kept_false(self) -> None:
        # MET/PRU — legitimate steady-state DDM, NOT suppressed.
        assert is_non_life_insurer("Insurance - Life") is False

    def test_brokers_banks_non_financials_false(self) -> None:
        assert is_non_life_insurer("Insurance - Brokers") is False  # asset-light fee
        assert is_non_life_insurer("Banks - Diversified") is False  # bank DDM is legit
        assert is_non_life_insurer("Asset Management") is False
        assert is_non_life_insurer("Software") is False
        assert is_non_life_insurer(None) is False
        assert is_non_life_insurer("") is False

    def test_stricter_than_balance_sheet_financial(self) -> None:
        # is_non_life_insurer ⊂ is_balance_sheet_financial: every name it suppresses is
        # a balance-sheet financial, but banks + life insurers are NOT in this cohort.
        for label in ("Insurance - Property & Casualty", "Insurance—Diversified"):
            assert is_non_life_insurer(label) and is_balance_sheet_financial(label)
        for label in ("Banks - Diversified", "Insurance - Life"):
            assert is_balance_sheet_financial(label) and not is_non_life_insurer(label)


class TestIsCommodityCyclical:
    """Full-basket regression钉死 for the cyclical gate (mechanical闸门).

    The provider industry tags below are the REAL ones (yfinance, probed
    2026-06-10 in scripts/_cyclical_*): MU/NVDA/AMD all carry "Semiconductors";
    WDC/STX carry "Computer Hardware" (so do DELL/ANET). The gate must therefore
    separate cyclicals from non-cyclicals WITHIN those shared buckets, never by
    the tag alone. AMD=False is the load-bearing assertion: a pure-volatility gate
    misclassifies AMD's turnaround swings as a commodity cycle (PILLAR 3).
    """

    def test_memory_storage_true_via_ticker_anchor(self) -> None:
        """Seed path: no description, generic tag — the ticker anchor fires.

        MU/NVDA/AMD share "Semiconductors"; WDC/STX share "Computer Hardware"
        with DELL/ANET. With only the tag available (the seed path), the curated
        anchor is what makes the memory/storage names cyclical."""
        assert is_commodity_cyclical("Semiconductors", "Technology", ticker="MU") is True
        assert is_commodity_cyclical("Computer Hardware", "Technology", ticker="WDC") is True
        assert is_commodity_cyclical("Computer Hardware", "Technology", ticker="STX") is True
        assert is_commodity_cyclical("Computer Hardware", "Technology", ticker="SNDK") is True

    def test_memory_storage_true_via_keyword(self) -> None:
        """Comps path: description carries a memory/storage keyword → cyclical,
        even for a ticker NOT in the anchor (the keyword收口 generalizes)."""
        assert (
            is_commodity_cyclical(
                "Semiconductors",
                "Technology",
                description="Designs and manufactures DRAM and NAND memory",
            )
            is True
        )
        assert (
            is_commodity_cyclical(
                "Computer Hardware",
                "Technology",
                description="Maker of hard disk drives and HDD storage",
            )
            is True
        )

    def test_non_cyclical_semis_false(self) -> None:
        """NVDA/AMD are "Semiconductors" but NOT memory — must stay non-cyclical.

        AMD=False even though its op-margin history is highly volatile: the gate
        is the whitelist/keyword/anchor, never volatility (the AMD假阳 the design
        rejected). No description, not in the anchor → False."""
        assert is_commodity_cyclical("Semiconductors", "Technology", ticker="NVDA") is False
        assert is_commodity_cyclical("Semiconductors", "Technology", ticker="AMD") is False
        # Even with a GPU/CPU description (no memory keyword) AMD stays False.
        assert (
            is_commodity_cyclical(
                "Semiconductors",
                "Technology",
                description="Designs CPUs, GPUs and adaptive SoC products",
                ticker="AMD",
            )
            is False
        )

    def test_non_cyclical_non_semis_false(self) -> None:
        assert (
            is_commodity_cyclical("Beverages—Non-Alcoholic", "Consumer Defensive", ticker="KO")
            is False
        )
        assert (
            is_commodity_cyclical("Software—Infrastructure", "Technology", ticker="MSFT") is False
        )
        assert (
            is_commodity_cyclical("Drug Manufacturers—General", "Healthcare", ticker="JNJ") is False
        )
        assert is_commodity_cyclical(industry=None, sector=None) is False

    def test_wide_bucket_without_keyword_false(self) -> None:
        """DELL/ANET sit in "Computer Hardware" but are not memory/storage → False
        (no anchor, no keyword)."""
        assert is_commodity_cyclical("Computer Hardware", "Technology", ticker="DELL") is False
        assert (
            is_commodity_cyclical(
                "Computer Hardware",
                "Technology",
                description="Network switches and routers",
                ticker="ANET",
            )
            is False
        )

    def test_unambiguous_cyclical_industries_true(self) -> None:
        """The unambiguous whitelist fires on the industry tag alone."""
        assert is_commodity_cyclical("Steel", "Basic Materials", ticker="X") is True
        assert is_commodity_cyclical("Oil & Gas E&P", "Energy", ticker="DVN") is True
        assert is_commodity_cyclical("Marine Shipping", "Industrials", ticker="ZIM") is True
        assert is_commodity_cyclical("Auto Manufacturers", "Consumer Cyclical", ticker="F") is True

    def test_live_fmp_dash_labels_classify_cyclical(self) -> None:
        """Matching must be immune to FMP's dash/space punctuation drift.

        FMP stable renamed the auto label "Auto Manufacturers" → "Auto - Manufacturers"
        (hyphen-space; live-verified 2026-06-15 across RIVN/TSLA/F/GM/STLA/LCID — all six
        return the identical 'Auto - Manufacturers'). The exact-match cyclical whitelist
        carried only "Auto Manufacturers" (no hyphen), so the ENTIRE auto sector silently
        lost cyclical classification + the comps_pb safety net after the v3→stable
        migration. (The bank whitelist already hedged both "Banks—Diversified" and
        "Banks - Diversified"; the cyclical one did not — sibling-position miss.) Matching
        must normalize dash variants (em-dash —, en-dash –, hyphen -) and surrounding
        whitespace so the live label classifies cyclical regardless of FMP punctuation."""
        assert (
            is_commodity_cyclical("Auto - Manufacturers", "Consumer Cyclical", ticker="F") is True
        )
        assert is_commodity_cyclical("Auto—Manufacturers", "Consumer Cyclical", ticker="GM") is True
        # The em-dash / hyphen-space variants of an unambiguous label must also match.
        assert is_commodity_cyclical("Oil & Gas E&P", "Energy", ticker="DVN") is True

    def test_fmp_stable_word_renamed_labels_classify_cyclical(self) -> None:
        """FMP stable WORD-renamed several cyclical labels — changes normalization cannot
        bridge (different words, not just punctuation), so the FMP-stable form must be
        ADDED to the whitelist alongside the legacy/yfinance form (providers carry
        different vocabularies; never delete the legacy form). Live-verified against
        FMP /available-industries (159 industries) 2026-06-15:
          'Oil & Gas E&P'      → 'Oil & Gas Exploration & Production'  (DVN/EOG silently dropped)
          'Specialty Chemicals'→ 'Chemicals - Specialty'
          'Coking Coal'        → 'Coal'
          (whitelist also lacked FMP's 'Other Precious Metals' — platinum/palladium)."""
        assert (
            is_commodity_cyclical("Oil & Gas Exploration & Production", "Energy", ticker="DVN")
            is True
        )
        assert (
            is_commodity_cyclical("Chemicals - Specialty", "Basic Materials", ticker="ALB") is True
        )
        assert is_commodity_cyclical("Coal", "Energy", ticker="BTU") is True
        assert (
            is_commodity_cyclical("Other Precious Metals", "Basic Materials", ticker="SBSW") is True
        )
        # FMP forms already whitelisted (controls — must stay True):
        assert is_commodity_cyclical("Steel", "Basic Materials", ticker="NUE") is True
        assert is_commodity_cyclical("Aluminum", "Basic Materials", ticker="AA") is True

    def test_ticker_anchor_normalizes_case_and_whitespace(self) -> None:
        assert is_commodity_cyclical("Semiconductors", "Technology", ticker=" mu ") is True


class TestCommodityCyclicalBasis:
    """Which arm fired — drives honest provenance + the memory-supercycle
    narrative scoping (TSLA must not read as a memory/storage name)."""

    def test_industry_whitelist_arm(self) -> None:
        assert commodity_cyclical_basis("Auto Manufacturers") == "industry"
        assert commodity_cyclical_basis("Steel") == "industry"

    def test_memory_storage_arm_for_generic_tags(self) -> None:
        # MU/WDC ride generic buckets — a True verdict there came from the
        # keyword收口 or the curated ticker anchor.
        assert commodity_cyclical_basis("Semiconductors") == "memory_storage"
        assert commodity_cyclical_basis("Computer Hardware") == "memory_storage"
        assert commodity_cyclical_basis(None) == "memory_storage"


class TestBankNetRevenue:
    def test_jpm_q1_2026_ties_to_sec(self) -> None:
        """73.661B gross − 23.825B interest expense = 49.836B = SEC net revenue."""
        assert bank_net_revenue(73_661_000_000, 23_825_000_000) == 49_836_000_000

    def test_missing_interest_expense_returns_none(self) -> None:
        """Caliber undefined when interest expense is missing — never re-serve the
        gross figure by treating a missing interest expense as 0."""
        assert bank_net_revenue(73_661_000_000, None) is None

    def test_missing_revenue_returns_none(self) -> None:
        assert bank_net_revenue(None, 23_825_000_000) is None

    def test_zero_interest_expense_passes_through(self) -> None:
        """A real reported 0 (not None) is a valid subtraction, not 'missing'."""
        assert bank_net_revenue(50_000_000_000, 0) == 50_000_000_000


class TestBankOperatingIncomeNetCaliber:
    """The net-revenue-caliber operating-income numerator for a bank's
    operating_margin. Values anchored to live FMP (JPM FY2025 annual):
    gross 279.745B, costAndExpenses 207.150B, operatingIncome 72.595B; the
    identity gross − costAndExpenses == OI holds, so the net-caliber OI == OI.
    """

    def test_identity_holds_returns_operating_income_unchanged(self) -> None:
        """When gross − costAndExpenses == operatingIncome (interest expense
        embedded in costAndExpenses), the net-revenue-caliber OI IS FMP's OI."""
        assert (
            bank_operating_income_net_caliber(279_745_000_000, 207_150_000_000, 72_595_000_000)
            == 72_595_000_000
        )

    def test_within_rounding_tolerance_passes(self) -> None:
        """A sub-bp rounding residual must not trip the guard."""
        assert (
            bank_operating_income_net_caliber(
                279_745_000_000, 207_150_000_000, 72_595_000_000 + 500_000
            )
            == 72_595_000_000 + 500_000
        )

    def test_identity_fails_abstains_to_none(self) -> None:
        """When the identity is violated beyond tolerance (interest expense
        placed OUTSIDE costAndExpenses → OI is gross-caliber), the net-caliber OI
        cannot be reconstructed — abstain to None, never emit a mixed caliber."""
        assert (
            bank_operating_income_net_caliber(
                279_745_000_000, 207_150_000_000, 72_595_000_000 - 10_000_000_000
            )
            is None
        )

    def test_missing_component_returns_none(self) -> None:
        assert bank_operating_income_net_caliber(None, 207_150_000_000, 72_595_000_000) is None
        assert bank_operating_income_net_caliber(279_745_000_000, None, 72_595_000_000) is None
        assert bank_operating_income_net_caliber(279_745_000_000, 207_150_000_000, None) is None


class TestSemiconductorRole:
    """Value-chain role split for the comps role gate. The IDM/foundry boundary
    is the load-bearing assertion: an IDM (designs+sells its OWN chips, owns fabs)
    is NOT a pure-play contract foundry, so it must NOT be a TSM/UMC/GFS comp.

    Descriptions below are the REAL FMP /profile text prefixes (live-verified
    2026-06-14). The earlier foundry_terms ("contract manufacturer",
    "manufactures, tests/packages") fired on IDMs and dragged NXPI/MCHP/ON/QRVO
    into a foundry comp set, diluting the foundry median. NXPI's "contract
    manufacturer" is a CUSTOMER type it serves; MCHP's "wafer foundry" is a
    subcontracting SERVICE line; ON's / QRVO's "foundry" is a govt/defense niche —
    none make them a foundry. The fix: a pure-play foundry IDENTITY term AND no
    IDM own-product-design identity.
    """

    # --- the 4 real pure-play foundries must classify as "foundry" ---

    def test_tsm_is_foundry(self) -> None:
        prof = {
            "company_name": "Taiwan Semiconductor Manufacturing Company Limited",
            "industry": "Semiconductors",
            "description": (
                "TSMC operates globally in the semiconductor industry, specializing in the "
                "manufacturing, packaging, and testing of integrated circuits. The company is "
                "renowned for its diverse array of wafer fabrication processes. Beyond its core "
                "foundry services, TSMC extends its offerings to engineering support."
            ),
        }
        assert semiconductor_role(prof) == "foundry"

    def test_umc_is_foundry(self) -> None:
        prof = {
            "company_name": "United Microelectronics Corporation",
            "industry": "Semiconductors",
            "description": (
                "United Microelectronics Corporation (UMC) operates as a specialized "
                "semiconductor wafer foundry, extending its services globally. Its customer base "
                "consists of both integrated device manufacturers and companies focused solely "
                "on chip design."
            ),
        }
        assert semiconductor_role(prof) == "foundry"

    def test_gfs_is_foundry(self) -> None:
        prof = {
            "company_name": "GLOBALFOUNDRIES Inc.",
            "industry": "Semiconductors",
            "description": (
                "GLOBALFOUNDRIES Inc. operates as a prominent global semiconductor foundry, "
                "specializing in the creation of integrated circuits. It offers comprehensive "
                "wafer fabrication services."
            ),
        }
        assert semiconductor_role(prof) == "foundry"

    def test_tsem_is_foundry(self) -> None:
        prof = {
            "company_name": "Tower Semiconductor Ltd.",
            "industry": "Semiconductors",
            "description": (
                "Tower Semiconductor Ltd. operates as a prominent independent semiconductor "
                "foundry, engaged in the worldwide production and sale of analog-intensive, "
                "mixed-signal semiconductor components. It offers wafer fabrication services and "
                "caters to both integrated device manufacturers and fabless companies."
            ),
        }
        assert semiconductor_role(prof) == "foundry"

    # --- the 4 IDMs with stray foundry mentions must NOT be "foundry" ---

    def test_nxpi_idm_not_foundry(self) -> None:
        """NXPI: "design and production"; "contract manufacturers" is a CUSTOMER type.
        Real text also "develops ... sensors" → design (not foundry)."""
        prof = {
            "company_name": "NXP Semiconductors N.V.",
            "industry": "Semiconductors",
            "description": (
                "NXP Semiconductors N.V. specializes in the design and production of a broad "
                "array of semiconductor solutions, including microcontrollers and application "
                "processors. The company also develops semiconductor-based sensors. NXP "
                "distributes its products globally, serving original equipment manufacturers "
                "(OEMs), contract manufacturers, and a network of distributors."
            ),
        }
        assert semiconductor_role(prof) == "design"

    def test_mchp_idm_not_foundry(self) -> None:
        """MCHP: "creates, produces, and sells"; "wafer foundry" is a subcontract service.
        Real text sells "embedded microprocessors" → design (not foundry)."""
        prof = {
            "company_name": "Microchip Technology Incorporated",
            "industry": "Semiconductors",
            "description": (
                "Microchip Technology Incorporated creates, produces, and sells intelligent, "
                "interconnected, and secure embedded control solutions, including 32-bit "
                "embedded microprocessors. Microchip delivers engineering services, along with "
                "wafer foundry, assembly, and test subcontracting manufacturing services."
            ),
        }
        assert semiconductor_role(prof) == "design"

    def test_on_idm_not_foundry(self) -> None:
        """ON: "designs and develops"; "foundry ... services ... for government clients" is a niche."""
        prof = {
            "company_name": "ON Semiconductor Corporation",
            "industry": "Semiconductors",
            "description": (
                "ON Semiconductor Corporation operates as a global provider of sophisticated "
                "power and sensing solutions. The firm designs and develops specialized analog, "
                "mixed-signal, and advanced logic products. Furthermore, it provides foundry and "
                "design services specifically for government clients."
            ),
        }
        assert semiconductor_role(prof) == "design"

    def test_qrvo_idm_not_foundry(self) -> None:
        """QRVO: "developing and bringing to market"; "compound semiconductor foundry
        services" is a defense-prime niche, not its identity."""
        prof = {
            "company_name": "Qorvo, Inc.",
            "industry": "Semiconductors",
            "description": (
                "Qorvo, Inc. is a global technology company focused on developing and bringing "
                "to market a diverse range of products for the wireless, wired, and power "
                "sectors, including RF power management integrated circuits. For defense primes, "
                "Qorvo supplies RF products and specialized compound semiconductor foundry "
                "services."
            ),
        }
        assert semiconductor_role(prof) == "design"

    # --- no regression on clear designers / equipment ---

    def test_clear_designer_is_design(self) -> None:
        prof = {
            "company_name": "NVIDIA Corporation",
            "industry": "Semiconductors",
            "description": "Designs and supplies GPUs and data center platforms for AI computing.",
        }
        assert semiconductor_role(prof) == "design"

    def test_equipment_vendor_is_equipment(self) -> None:
        prof = {
            "company_name": "ASML Holding N.V.",
            "industry": "Semiconductors",
            "description": (
                "Develops and services semiconductor equipment systems including lithography "
                "machines for chipmakers."
            ),
        }
        assert semiconductor_role(prof) == "equipment"

    def test_non_semiconductor_returns_none(self) -> None:
        assert semiconductor_role({"description": "Manufactures and sells beverages."}) is None
        assert semiconductor_role(None) is None

    def test_no_semiconductor_token_anywhere_returns_none(self) -> None:
        """A profile with no semiconductor token in ANY field (name/industry/sector/
        description) is role-unknown — Seagate/STX is the live example: "global
        provider of data storage technology; hard disk drives", zero chip/wafer/
        semiconductor words → None, which the role gate treats as incompatible
        (the very reason the curated cohort must be PROTECTED in peer_screen)."""
        prof = {
            "company_name": "Seagate Technology Holdings plc",
            "industry": "Computer Hardware",
            "description": "Global provider of advanced data storage technology; hard disk drives.",
        }
        assert semiconductor_role(prof) is None

    def test_industry_tag_alone_classifies_as_semiconductor_other(self) -> None:
        """The "Semiconductors" industry tag alone trips the token gate (it is part of
        ``profile_text``), so a profile with that tag but no role-specific term lands in
        the generic semiconductor_other bucket — not None."""
        assert (
            semiconductor_role({"company_name": "X", "industry": "Semiconductors"})
            == "semiconductor_other"
        )
