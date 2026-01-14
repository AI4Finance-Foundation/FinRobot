"""
Asesor IA de Inversiones
Usa GPT-4o para generar recomendaciones personalizadas.
"""
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

from config import get_openai_api_key, ETFS_RECOMENDADOS, PERFILES_RIESGO

logger = logging.getLogger("AIAdvisor")


class AIAdvisor:
    """
    Asesor de inversiones basado en GPT-4o.
    Genera recomendaciones personalizadas según el perfil del inversor.
    """
    
    def __init__(self):
        self.api_key = get_openai_api_key()
        self.client = None
        self._init_client()
    
    def _init_client(self):
        """Inicializa el cliente de OpenAI"""
        if not self.api_key:
            logger.error("❌ No se encontró API key de OpenAI")
            return
        
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=self.api_key)
            logger.info("✅ Cliente OpenAI inicializado")
        except ImportError:
            logger.error("❌ Instala openai: pip install openai")
    
    def _call_gpt(self, system_prompt: str, user_prompt: str, 
                  temperature: float = 0.2, max_tokens: int = 2000) -> Optional[str]:
        """Llama a GPT-4o y retorna la respuesta"""
        if not self.client:
            return "Error: Cliente OpenAI no inicializado"
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=temperature,
                max_tokens=max_tokens
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"❌ Error llamando a GPT: {e}")
            return f"Error: {str(e)}"
    
    def generar_distribucion_personalizada(self, perfil: Dict) -> Dict[str, Any]:
        """
        Genera una distribución de activos personalizada según el perfil.
        
        Args:
            perfil: {
                'edad': 52,
                'horizonte_anos': 15,
                'tolerancia_riesgo': 'agresivo',
                'objetivo': 'crecimiento',
                'aportacion_mensual': 3000,
                'restricciones': ['no_vender_cripto']
            }
        
        Returns:
            {
                'distribucion': {'renta_variable': 0.60, ...},
                'justificacion': '...',
                'consideraciones': ['...']
            }
        """
        system_prompt = """Eres un asesor financiero certificado especializado en gestión de patrimonios.
Tu tarea es diseñar distribuciones de activos personalizadas basadas en el perfil del inversor.
Responde SIEMPRE en JSON válido con la estructura especificada."""

        user_prompt = f"""
Diseña una distribución de activos para este perfil de inversor:

PERFIL:
- Edad: {perfil.get('edad', 50)} años
- Horizonte de inversión: {perfil.get('horizonte_anos', 10)} años
- Tolerancia al riesgo: {perfil.get('tolerancia_riesgo', 'moderado')}
- Objetivo: {perfil.get('objetivo', 'crecimiento')}
- Aportación mensual: €{perfil.get('aportacion_mensual', 0):,.0f}
- Restricciones: {perfil.get('restricciones', [])}

Responde en JSON con esta estructura exacta:
{{
    "distribucion": {{
        "renta_variable": 0.XX,
        "renta_fija": 0.XX,
        "oro": 0.XX,
        "cripto": 0.XX,
        "liquidez": 0.XX
    }},
    "justificacion": "Explicación breve de por qué esta distribución es adecuada",
    "consideraciones": ["Punto 1", "Punto 2", "Punto 3"]
}}

La suma de porcentajes debe ser 1.0 (100%).
"""
        
        response = self._call_gpt(system_prompt, user_prompt, temperature=0.1)
        
        try:
            # Extraer JSON de la respuesta
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                response = response.split("```")[1].split("```")[0]
            
            return json.loads(response)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            # Fallback: usar perfil predefinido (parsing failed: {e})
            perfil_riesgo = PERFILES_RIESGO.get(perfil.get('tolerancia_riesgo', 'moderado'))
            return {
                'distribucion': perfil_riesgo['distribucion'],
                'justificacion': f"Distribución basada en perfil {perfil_riesgo['nombre']}",
                'consideraciones': [perfil_riesgo['descripcion']]
            }
    
    def generar_cartera_desde_cero(self, capital: float, perfil: Dict) -> Dict[str, Any]:
        """
        Genera una cartera completa desde cero con activos específicos.
        
        Args:
            capital: Capital disponible para invertir
            perfil: Perfil del inversor
            
        Returns:
            {
                'cartera': [
                    {'ticker': 'IWDA.AS', 'nombre': '...', 'porcentaje': 40, 'monto': 40000},
                    ...
                ],
                'distribucion_resultante': {...},
                'justificacion': '...'
            }
        """
        # Obtener ETFs disponibles como contexto
        etfs_context = json.dumps(ETFS_RECOMENDADOS, indent=2)
        
        system_prompt = """Eres un asesor financiero certificado especializado en construcción de carteras.
Tu tarea es diseñar carteras de inversión concretas con activos específicos.
Responde SIEMPRE en JSON válido con la estructura especificada.
Usa solo ETFs disponibles en brokers europeos (Ticker.AS para Amsterdam, .DE para Alemania, etc.)."""

        user_prompt = f"""
Diseña una cartera de inversión completa para este perfil:

PERFIL:
- Edad: {perfil.get('edad', 50)} años
- Horizonte: {perfil.get('horizonte_anos', 10)} años
- Tolerancia al riesgo: {perfil.get('tolerancia_riesgo', 'moderado')}
- Objetivo: {perfil.get('objetivo', 'crecimiento')}
- CAPITAL DISPONIBLE: €{capital:,.0f}
- Restricciones: {perfil.get('restricciones', [])}

ETFs DISPONIBLES (referencia):
{etfs_context}

Responde en JSON con esta estructura:
{{
    "cartera": [
        {{"ticker": "IWDA.AS", "nombre": "iShares MSCI World", "categoria": "renta_variable", "porcentaje": 40, "monto": 40000, "justificacion": "Core de RV global"}},
        ...
    ],
    "distribucion_resultante": {{
        "renta_variable": {{"porcentaje": 60, "monto": 60000}},
        "renta_fija": {{"porcentaje": 25, "monto": 25000}},
        "oro": {{"porcentaje": 5, "monto": 5000}},
        "cripto": {{"porcentaje": 5, "monto": 5000}},
        "liquidez": {{"porcentaje": 5, "monto": 5000}}
    }},
    "justificacion": "Explicación de la estrategia",
    "proximos_pasos": ["Paso 1", "Paso 2"]
}}

Incluye 5-8 activos diversificados. El total debe sumar €{capital:,.0f}.
"""
        
        response = self._call_gpt(system_prompt, user_prompt, temperature=0.2, max_tokens=2500)
        
        try:
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                response = response.split("```")[1].split("```")[0]
            return json.loads(response)
        except Exception as e:
            return {"error": str(e), "respuesta_raw": response}
    
    def generar_plan_rebalanceo(self, resumen_portfolio: Dict, capital_nuevo: float = 0) -> str:
        """
        Genera un plan de rebalanceo detallado para un portfolio existente.
        
        Args:
            resumen_portfolio: Resumen del portfolio (de portfolio.generar_resumen())
            capital_nuevo: Capital adicional disponible
            
        Returns:
            Plan de rebalanceo en texto Markdown
        """
        system_prompt = """Eres un asesor financiero experto en gestión de patrimonios con enfoque práctico.

REGLAS IMPORTANTES:
1. NUNCA sugieras vender todas las posiciones - eso es impracticable
2. Prioriza usar el capital nuevo disponible antes de vender
3. Los rebalanceos deben ser GRADUALES, no drásticos
4. Respeta las posiciones con buen P&L (>10%) - no vendas ganadores
5. Considera costes fiscales de las ventas

Responde en español con formato Markdown claro y estructurado."""

        # Construir detalle de posiciones
        posiciones_texto = "\n".join([
            f"- {p.get('nombre', 'N/A')}: €{p.get('valor', p.get('valor_actual', 0)):,.0f} ({p.get('tipo', p.get('categoria', 'N/A'))}) - P&L: {((p.get('valor', 0)/p.get('coste', 1))-1)*100 if p.get('coste', 0) > 0 else 0:+.1f}%"
            for p in resumen_portfolio.get('posiciones', {}).values()
        ])
        
        # Construir tabla de distribución - usar los nombres correctos de campos
        dist = resumen_portfolio.get('distribucion', {})
        desv = resumen_portfolio.get('desviaciones', {})
        
        dist_texto = "| Categoría | Actual | Objetivo | Desviación |\n|-----------|--------|----------|------------|\n"
        for cat in ['renta_variable', 'renta_fija', 'oro', 'cripto', 'liquidez']:
            cat_data = desv.get(cat, {})
            # Soportar ambos formatos de nombres de campos
            actual = cat_data.get('actual_pct', cat_data.get('actual', 0))
            objetivo = cat_data.get('objetivo_pct', cat_data.get('objetivo', 0))
            desviacion = cat_data.get('desviacion_pct', cat_data.get('desviacion', 0))
            dist_texto += f"| {cat.replace('_', ' ').title()} | {actual:.1f}% | {objetivo:.1f}% | {desviacion:+.1f}% |\n"
        
        perfil = resumen_portfolio.get('perfil', {})
        restricciones = perfil.get('restricciones', [])
        
        # Calcular capital total disponible para rebalanceo
        liquidez_actual = desv.get('liquidez', {}).get('actual_pct', 0)
        valor_total = resumen_portfolio.get('valor_total', 0)
        
        user_prompt = f"""
Genera un plan de rebalanceo PRÁCTICO y GRADUAL para este portfolio:

**PERFIL DEL INVERSOR:**
- Edad: {perfil.get('edad', 50)} años
- Horizonte: {perfil.get('horizonte_anos', 10)} años  
- Tolerancia al riesgo: {perfil.get('tolerancia_riesgo', 'moderado')}
- Restricciones: {restricciones if restricciones else 'Ninguna específica'}
- Capital nuevo disponible: €{capital_nuevo:,.0f}

**VALOR TOTAL CARTERA:** €{valor_total:,.0f}
**P&L TOTAL:** {resumen_portfolio.get('pnl_pct', 0):+.1f}%

**POSICIONES ACTUALES (NO VENDER TODAS, solo optimizar):**
{posiciones_texto}

**DISTRIBUCIÓN ACTUAL vs OBJETIVO:**
{dist_texto}

**INSTRUCCIONES:**
- Usa PRINCIPALMENTE el capital nuevo (€{capital_nuevo:,.0f}) y la liquidez existente para rebalancear
- Si hay que vender algo, que sea MÍNIMO y justificado (posiciones con pérdidas o muy sobreponderadas)
- NO sugieras vender posiciones con P&L positivo alto
- Propón movimientos concretos con montos específicos en €

Estructura tu respuesta así:
1. **DIAGNÓSTICO** (2-3 líneas): Qué desequilibrios hay
2. **ACCIONES CON CAPITAL NUEVO** (€{capital_nuevo:,.0f}): Dónde invertirlo
3. **AJUSTES INTERNOS** (solo si necesario): Movimientos entre posiciones existentes
4. **RESUMEN DE OPERACIONES**: Tabla con Acción | Activo | Monto
"""
        
        return self._call_gpt(system_prompt, user_prompt, temperature=0.2, max_tokens=2000)
    
    def obtener_ideas_inversion(self, sector: Optional[str] = None, 
                                 perfil_riesgo: str = 'moderado') -> str:
        """
        Genera ideas de inversión específicas.
        
        Args:
            sector: Filtro por sector (opcional)
            perfil_riesgo: Nivel de riesgo del inversor
            
        Returns:
            Ideas en formato Markdown
        """
        system_prompt = """Eres un analista financiero experto.
Tu tarea es identificar oportunidades de inversión específicas y bien fundamentadas.
Responde en español con formato Markdown."""

        sector_filtro = f"Enfócate en el sector: {sector}" if sector else "Considera todos los sectores"
        
        user_prompt = f"""
Fecha: {datetime.now().strftime('%Y-%m-%d')}

CONTEXTO:
- Inversor europeo
- Perfil de riesgo: {perfil_riesgo}
- {sector_filtro}

Genera 3-5 IDEAS DE INVERSIÓN actuales.

Para cada idea incluye:
1. **Nombre y Ticker** (preferiblemente accesible desde brokers europeos)
2. **Tipo**: Acción, ETF, Fondo
3. **Tesis de inversión** (2-3 frases)
4. **Catalizadores** a corto plazo
5. **Riesgos** principales
6. **Puntuación de convicción**: 1-10

Sé concreto y fundamenta cada idea.
"""
        
        return self._call_gpt(system_prompt, user_prompt, temperature=0.3, max_tokens=1500)
    
    def analisis_rapido(self, resumen_portfolio: Dict) -> str:
        """
        Genera un análisis rápido del estado del portfolio.
        
        Args:
            resumen_portfolio: Resumen del portfolio
            
        Returns:
            Análisis breve en Markdown
        """
        system_prompt = """Eres un asesor financiero conciso.
Proporciona análisis breves y accionables. Máximo 200 palabras.
Responde en español."""

        dist = resumen_portfolio.get('distribucion', {})
        
        user_prompt = f"""
Analiza este portfolio brevemente:

- Valor total: €{resumen_portfolio.get('valor_total', 0):,.0f}
- P&L: {resumen_portfolio.get('pnl_pct', 0):+.1f}%
- Necesita rebalanceo: {'Sí' if resumen_portfolio.get('necesita_rebalanceo') else 'No'}

Distribución actual:
- RV: {dist.get('renta_variable', {}).get('pct', 0):.1f}%
- RF: {dist.get('renta_fija', {}).get('pct', 0):.1f}%
- Oro: {dist.get('oro', {}).get('pct', 0):.1f}%
- Cripto: {dist.get('cripto', {}).get('pct', 0):.1f}%
- Liquidez: {dist.get('liquidez', {}).get('pct', 0):.1f}%

Dame:
1. Estado general (1 frase)
2. Principal preocupación (si hay)
3. Una acción recomendada
"""
        
        return self._call_gpt(system_prompt, user_prompt, temperature=0.2, max_tokens=400)


# Singleton
_advisor = None

def get_advisor() -> AIAdvisor:
    """Obtiene la instancia singleton del AIAdvisor"""
    global _advisor
    if _advisor is None:
        _advisor = AIAdvisor()
    return _advisor

