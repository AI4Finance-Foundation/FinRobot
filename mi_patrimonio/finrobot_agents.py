"""
Integración con Agentes Reales de FinRobot
Usa Market_Analyst y Financial_Analyst para enriquecer el análisis.
"""
import os
import sys
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

# Añadir FinRobot al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import autogen
from autogen.cache import Cache

# Early logger for startup
_startup_logger = logging.getLogger(__name__)

# Cargar API keys antes de importar FinRobot
def _load_api_keys():
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config_api_keys")
    try:
        with open(config_path) as f:
            keys = json.load(f)
        for key, value in keys.items():
            os.environ[key] = value
        _startup_logger.info("API keys loaded: %s", list(keys.keys()))
    except FileNotFoundError:
        _startup_logger.debug("API keys file not found, using environment variables")
    except (json.JSONDecodeError, PermissionError) as e:
        _startup_logger.warning("Could not load API keys: %s", e)

_load_api_keys()

from finrobot.agents.workflow import SingleAssistant, FinRobot
from finrobot.data_source import FinnHubUtils, YFinanceUtils, FMPUtils

logger = logging.getLogger("FinRobotAgents")

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN LLM
# ═══════════════════════════════════════════════════════════════════════════════
def get_llm_config():
    """Obtiene la configuración LLM desde OAI_CONFIG_LIST"""
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "OAI_CONFIG_LIST")
    try:
        config_list = autogen.config_list_from_json(
            config_path,
            filter_dict={"model": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"]}
        )
        return {
            "config_list": config_list,
            "timeout": 120,
            "temperature": 0.3
        }
    except Exception as e:
        logger.error(f"Error cargando config: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIONES DE ANÁLISIS DIRECTO (sin agentes multi-turn)
# ═══════════════════════════════════════════════════════════════════════════════
class FinRobotAnalyzer:
    """
    Usa las herramientas de FinRobot directamente para análisis rápido.
    """
    
    def __init__(self):
        self.llm_config = get_llm_config()
        logger.info("✅ FinRobotAnalyzer inicializado")
    
    def obtener_noticias_ticker(self, ticker: str, dias: int = 7) -> List[Dict]:
        """
        Obtiene noticias recientes de un ticker usando FinnHub.
        """
        try:
            from datetime import datetime, timedelta
            end = datetime.now()
            start = end - timedelta(days=dias)
            
            noticias = FinnHubUtils.get_company_news(
                ticker, 
                start.strftime('%Y-%m-%d'), 
                end.strftime('%Y-%m-%d')
            )
            
            if isinstance(noticias, str):
                # FinnHub devuelve string formateado
                return [{"raw": noticias}]
            return noticias[:10] if noticias else []
            
        except Exception as e:
            logger.warning(f"Error obteniendo noticias de {ticker}: {e}")
            return []
    
    def obtener_perfil_empresa(self, ticker: str) -> Dict:
        """
        Obtiene el perfil de una empresa usando FinnHub.
        """
        try:
            perfil = FinnHubUtils.get_company_profile(ticker)
            return perfil if perfil else {}
        except Exception as e:
            logger.warning(f"Error obteniendo perfil de {ticker}: {e}")
            return {}
    
    def obtener_financials(self, ticker: str) -> Dict:
        """
        Obtiene métricas financieras básicas usando FinnHub.
        """
        try:
            financials = FinnHubUtils.get_basic_financials(ticker)
            return financials if financials else {}
        except Exception as e:
            logger.warning(f"Error obteniendo financials de {ticker}: {e}")
            return {}
    
    def obtener_datos_mercado(self, ticker: str, periodo: str = "1mo") -> Dict:
        """
        Obtiene datos de mercado usando YFinance.
        """
        try:
            datos = YFinanceUtils.get_stock_data(ticker, periodo)
            return {"data": datos} if datos else {}
        except Exception as e:
            logger.warning(f"Error obteniendo datos de {ticker}: {e}")
            return {}
    
    def analizar_sentimiento_mercado(self, tickers: List[str]) -> Dict[str, Any]:
        """
        Analiza el sentimiento del mercado para una lista de tickers.
        Combina noticias y datos de mercado.
        """
        resultado = {
            "timestamp": datetime.now().isoformat(),
            "tickers_analizados": tickers,
            "analisis": {}
        }
        
        for ticker in tickers[:5]:  # Limitar a 5 para no sobrecargar
            logger.info(f"📊 Analizando {ticker}...")
            
            ticker_data = {
                "noticias": self.obtener_noticias_ticker(ticker, dias=7),
                "financials": self.obtener_financials(ticker),
            }
            
            resultado["analisis"][ticker] = ticker_data
        
        return resultado


# ═══════════════════════════════════════════════════════════════════════════════
# AGENTE DE ANÁLISIS CON GPT (usando contexto de FinRobot)
# ═══════════════════════════════════════════════════════════════════════════════
class FinRobotAdvisor:
    """
    Combina datos de FinRobot con GPT-4o para análisis y recomendaciones.
    """
    
    def __init__(self):
        self.analyzer = FinRobotAnalyzer()
        self.llm_config = get_llm_config()
        self._init_openai()
    
    def _init_openai(self):
        """Inicializa cliente OpenAI directo para respuestas rápidas"""
        try:
            from openai import OpenAI
            # Obtener API key del config
            config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "OAI_CONFIG_LIST")
            with open(config_path) as f:
                config = json.load(f)
            api_key = config[0].get("api_key") if config else None
            self.client = OpenAI(api_key=api_key)
            logger.info("✅ Cliente OpenAI inicializado")
        except Exception as e:
            logger.error(f"Error inicializando OpenAI: {e}")
            self.client = None
    
    def _call_gpt(self, system: str, user: str, max_tokens: int = 2000) -> str:
        """Llama a GPT-4o"""
        if not self.client:
            return "Error: Cliente OpenAI no disponible"
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user}
                ],
                temperature=0.3,
                max_tokens=max_tokens
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Error: {e}"
    
    def analizar_mercado_para_rebalanceo(self, tickers: List[str]) -> str:
        """
        Usa FinRobot para obtener datos y GPT para análisis.
        """
        logger.info(f"🔍 Analizando mercado con FinRobot para: {tickers}")
        
        # 1. Obtener datos con herramientas de FinRobot
        datos_mercado = self.analyzer.analizar_sentimiento_mercado(tickers)
        
        # 2. Formatear para GPT
        datos_texto = json.dumps(datos_mercado, indent=2, default=str)[:4000]
        
        system_prompt = """Eres el Market_Analyst de FinRobot.
Tu rol es analizar datos de mercado (noticias, financials) y dar un resumen ejecutivo.
Responde en español, sé conciso y accionable."""

        user_prompt = f"""
Analiza estos datos de mercado obtenidos por FinRobot:

{datos_texto}

Proporciona:
1. **SENTIMIENTO GENERAL**: Bullish/Neutral/Bearish para cada ticker
2. **NOTICIAS RELEVANTES**: Resumen de lo más importante
3. **ALERTAS**: Si hay algo que requiera atención inmediata
4. **IMPLICACIONES**: Cómo afecta esto a decisiones de inversión

Sé breve pero informativo.
"""
        
        return self._call_gpt(system_prompt, user_prompt)
    
    def generar_rebalanceo_con_contexto(
        self, 
        resumen_portfolio: Dict, 
        capital_nuevo: float = 0
    ) -> str:
        """
        Genera plan de rebalanceo enriquecido con datos de FinRobot.
        """
        # 1. Extraer tickers del portfolio
        tickers = []
        for pos in resumen_portfolio.get('posiciones', {}).values():
            ticker = pos.get('ticker')
            if ticker:
                tickers.append(ticker)
        
        # Añadir índices de referencia
        tickers.extend(['SPY', 'QQQ', 'GLD'])
        tickers = list(set(tickers))[:8]  # Limitar
        
        # 2. Obtener análisis de mercado con FinRobot
        logger.info("📈 Obteniendo contexto de mercado con FinRobot...")
        contexto_mercado = self.analizar_mercado_para_rebalanceo(tickers)
        
        # 3. Construir prompt enriquecido
        posiciones_texto = "\n".join([
            f"- {p.get('nombre', 'N/A')}: €{p.get('valor', 0):,.0f} ({p.get('tipo', 'N/A')}) - P&L: {p.get('pnl_pct', 0):+.1f}%"
            for p in resumen_portfolio.get('posiciones', {}).values()
        ])
        
        desv = resumen_portfolio.get('desviaciones', {})
        dist_texto = "| Categoría | Actual | Objetivo | Desviación |\n|-----------|--------|----------|------------|\n"
        for cat in ['renta_variable', 'renta_fija', 'oro', 'cripto', 'liquidez']:
            cat_data = desv.get(cat, {})
            actual = cat_data.get('actual_pct', 0)
            objetivo = cat_data.get('objetivo_pct', 0)
            desviacion = cat_data.get('desviacion_pct', 0)
            dist_texto += f"| {cat.replace('_', ' ').title()} | {actual:.1f}% | {objetivo:.1f}% | {desviacion:+.1f}% |\n"
        
        perfil = resumen_portfolio.get('perfil', {})
        
        system_prompt = """Eres FinRobot, un sistema de IA financiera que combina:
- Market_Analyst: Para sentimiento y noticias
- Financial_Analyst: Para métricas fundamentales
- Portfolio Advisor: Para recomendaciones de rebalanceo

REGLAS:
1. NUNCA sugieras vender todas las posiciones
2. Prioriza el capital nuevo antes de vender
3. Los rebalanceos deben ser GRADUALES
4. Considera el contexto de mercado actual
5. Respeta posiciones con buen P&L

Responde en español con formato Markdown."""

        user_prompt = f"""
## CONTEXTO DE MERCADO (de FinRobot Market_Analyst)

{contexto_mercado}

---

## PORTFOLIO A REBALANCEAR

**Perfil del Inversor:**
- Edad: {perfil.get('edad', 50)} años
- Horizonte: {perfil.get('horizonte_anos', 10)} años
- Tolerancia al riesgo: {perfil.get('tolerancia_riesgo', 'moderado')}

**Valor Total:** €{resumen_portfolio.get('valor_total', 0):,.0f}
**Capital Nuevo Disponible:** €{capital_nuevo:,.0f}

**Posiciones Actuales:**
{posiciones_texto}

**Distribución Actual vs Objetivo:**
{dist_texto}

---

## SOLICITUD

Genera un plan de rebalanceo que:
1. Tenga en cuenta el contexto de mercado actual
2. Use principalmente el capital nuevo (€{capital_nuevo:,.0f})
3. Sea específico con montos y tickers
4. Incluya timing sugerido (ahora vs esperar)

Estructura:
1. **DIAGNÓSTICO** (basado en datos de mercado)
2. **ACCIONES RECOMENDADAS** (con montos específicos)
3. **TIMING** (cuándo ejecutar cada acción)
4. **RESUMEN** (tabla de operaciones)
"""
        
        return self._call_gpt(system_prompt, user_prompt, max_tokens=2500)
    
    def obtener_ideas_inversion_finrobot(self, perfil_riesgo: str = 'moderado') -> str:
        """
        Genera ideas de inversión usando datos de FinRobot.
        """
        # Tickers populares para análisis
        tickers_analizar = ['SPY', 'QQQ', 'AAPL', 'MSFT', 'NVDA', 'GLD', 'TLT']
        
        # Obtener datos con FinRobot
        datos = self.analyzer.analizar_sentimiento_mercado(tickers_analizar)
        datos_texto = json.dumps(datos, indent=2, default=str)[:3000]
        
        system_prompt = """Eres FinRobot Expert_Investor.
Tu rol es identificar oportunidades de inversión basándote en datos de mercado reales.
Responde en español, sé específico con tickers y fundamenta cada idea."""

        user_prompt = f"""
## DATOS DE MERCADO (FinRobot)

{datos_texto}

## PERFIL

Inversor europeo con perfil de riesgo: {perfil_riesgo}
Fecha: {datetime.now().strftime('%Y-%m-%d')}

## SOLICITUD

Genera 3-5 ideas de inversión concretas basándote en:
1. Los datos de mercado obtenidos
2. Tendencias actuales
3. Oportunidades de valor

Para cada idea incluye:
- **Ticker y Nombre**
- **Tipo**: ETF, Acción, Fondo
- **Tesis** (2-3 frases)
- **Catalizadores** próximos
- **Riesgo principal**
- **Convicción**: 1-10

Sé específico y fundamenta con los datos.
"""
        
        return self._call_gpt(system_prompt, user_prompt, max_tokens=1500)


# ═══════════════════════════════════════════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════════════════════════════════════════
_finrobot_advisor = None

def get_finrobot_advisor() -> FinRobotAdvisor:
    """Obtiene instancia singleton de FinRobotAdvisor"""
    global _finrobot_advisor
    if _finrobot_advisor is None:
        _finrobot_advisor = FinRobotAdvisor()
    return _finrobot_advisor


# ═══════════════════════════════════════════════════════════════════════════════
# TEST
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    advisor = get_finrobot_advisor()
    
    print("\n" + "="*60)
    print("TEST: Análisis de mercado con FinRobot")
    print("="*60)
    
    resultado = advisor.analizar_mercado_para_rebalanceo(['AAPL', 'SPY'])
    print(resultado)

