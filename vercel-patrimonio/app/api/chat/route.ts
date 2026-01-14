import { NextResponse } from 'next/server'
import OpenAI from 'openai'
import { ChatRequestSchema, validateRequest } from '@/lib/validation'

// Lazy initialization para evitar errores durante el build
let openai: OpenAI | null = null
function getOpenAI() {
  if (!openai) {
    openai = new OpenAI({
      apiKey: process.env.OPENAI_API_KEY || 'dummy-key-for-build',
    })
  }
  return openai
}

// Contextos por portfolio
const PORTFOLIO_CONTEXTS = {
  salva: `Estás respondiendo sobre el patrimonio de **Salvador Carrillo Bardo (Salva)** también conocido como Carrillo Sánchez.

DATOS DEL PATRIMONIO (Actualizado 06/01/2026):
- Valor Total: €748,549 (incluye Indexa €215k + Bankinter €42k + Andbank €357k + Oro €36k + Cripto €97k)
- P&L: +€45,320 (+6.4%)
- Posiciones: 18 (Indexa 12 + Bankinter 5 + Andbank 1)
- Necesita Rebalanceo: SÍ - URGENTE (21.6% RV vs 60% objetivo)
- Edad: 52 años
- Horizonte: 15 años
- Tolerancia: Agresivo

DISTRIBUCIÓN ACTUAL (VERIFICADA 06/01):
- Renta Variable: 21.6% (€161k) vs objetivo 60% → -38.4% CRÍTICO ⚠️
- Renta Fija: 34.6% (€259k) vs objetivo 30% → +4.6%
- Oro: 4.9% (€36k) vs objetivo 5% → OK
- Liquidez: 26.0% (€195k) vs objetivo 5% → +21% MUY ALTO
- Cripto: 13.0% (€97k) → Pérdidas -52.5%

LIQUIDEZ DISPONIBLE PARA INVERTIR:
- Andbank (Sociedad): €183,187.67 ✅ LISTO
- Bankinter (Personal): €11,318.00

ESTRUCTURA FISCAL:
- 70% Sociedad (Andbank)
- 30% Personal (Bankinter + Indexa Capital)

POSICIONES ACTUALES VERIFICADAS:
INDEXA CAPITAL (€215,867):
- Vanguard US 500: €56,345
- Vanguard European: €33,769
- 10 fondos más Vanguard (RF + RV global)

BANKINTER (€41,764):
- EXXY (Basic Resources): €3,271 ✅
- ICOM (Commodities): €9,273 ✅
- 2B76 (Basic Resources): €10,024 ✅
- NUKL (Uranium): €4,997 ✅
- XRS2 (Russell 2000): €2,881 → PENDIENTE VENTA 9 títulos
- Liquidez: €11,318

ANDBANK (€357,188):
- WF Euro Credit (Remanente): €174,000
- Liquidez: €183,188 ✅ LISTO PARA FASE 1

FASE 0 - VENTAS EJECUTADAS (Diciembre 2025 + Enero 2026):
Total liquidez generada: €179,589
- ITA (€13,125), IWM (€11,135), BOTZ (€21,043), INDA (€8,962)
- WF Euro Credit PARCIAL (€117,000)
- XRS2 PARCIAL (€8,324) → Quedan 9 títulos por vender

FASE 1 - ESTADO ACTUAL (06/01/2026):
✅ EJECUTADAS Bankinter (05/01/26): €27,565
- EXXY: €3,271 (120 títulos @ €27.260)
- ICOM: €9,273 (270 títulos @ €34.345)
- 2B76: €10,024 (2,208 títulos @ €4.54)
- NUKL: €4,997 (100 títulos @ €49.970)

⏳ PENDIENTES Andbank (Planificado 09-10/01):
- VUAA Vanguard U.S. 500: €150,000 (Sociedad)
- PIMCO Income EUR Hedged: €17,000 (Personal)

⚠️ ACCIÓN PENDIENTE:
- Vender 9 títulos XRS2 Russell 2000 (€2,881)

PRÓXIMAS FASES:
Fase 2 (Feb): NUKL ampliar €4k, Healthcare €25k, India €25k
Fase 3-4 (Mar-Abr): NVDA €15k, GEV €15k, DFEN €15k

SITUACIÓN CRÍTICA:
El portfolio tiene solo 21.6% en RV vs objetivo 60% tras las ventas de Fase 0.
Es URGENTE ejecutar VUAA €150k en Andbank para rebalancear.`,

  madre: `Estás respondiendo sobre el patrimonio **Carrillo Bardo (Mamá)**.

DATOS DEL PATRIMONIO:
- Valor Total: €2,266,410 (€2.27M)
- P&L: +€621,040 (+37.7%)
- Posiciones: 12 (post-ventas Andbank)
- Necesita Rebalanceo: SÍ (€704k liquidez para invertir)
- Edad: 75 años
- Horizonte: 10 años
- Tolerancia: Moderada (media-alta)

DISTRIBUCIÓN ACTUAL (REAL):
- Renta Variable: 48% (objetivo 55%) → -7% desviación
- Renta Fija: 31% (objetivo 30%) → +1% OK
- Oro: 0% (objetivo 3%) → -3% desviación
- Liquidez: 16% (objetivo 7%) → +9% ALTO
  (Incluye Cripto: Bitcoin €360k + Ethereum €9k)

ESTRUCTURA FISCAL:
- 100% Personal (Andbank/Indexa/Cartesio)
- Sin sociedad

POSICIONES PRINCIPALES ACTUALES:
- Indexa Capital: €605k
- Cartesio X: €428k (Fondo mixto conservador)
- Bitcoin: €360k (Plusvalía €260k EXENTA)
- SIH Ahorro: €286k
- Otros fondos Andbank: €313k

PLAN ESTRATÉGICO 2026 - LIQUIDEZ €704,156:

FASE 1 (10-15 Enero) - Core Conservador €528k:
- VUAA Vanguard U.S. 500: €200k
- IYH iShares Health Care: €100k
- Fondo Monetario: €160k
- PGLD Amundi Gold: €68k

FASE 2 (20-25 Enero) - Alpha Controlado €130k:
- RHHBY Roche: €40k (dividendo, GLP-1)
- LLY Eli Lilly: €40k (líder GLP-1)
- IUUS iShares Utilities: €50k (nuclear)

FASE 3 (Febrero) - Completar €46k:
- NUKL VanEck Uranium: €25k
- DFEN VanEck Defense: €21k

ESTRATEGIA FinRobot:
- Equilibrio conservador con alpha controlado
- Bitcoin como activo de herencia (exento)
- Exposición directa a líderes salud (Lilly, Roche)
- Tema nuclear completo (Utilities + Uranium)`,

  consolidado: `Estás respondiendo sobre el **patrimonio consolidado de la familia Carrillo-Bardo**.

PATRIMONIO TOTAL FAMILIA:
- Valor Total: €3,176,626 (€3.18M)
- P&L Total: +€666,360 (+26.5%)
- Posiciones Totales: 24

COMPOSICIÓN:
1. Salvador Carrillo Sánchez (Salva):
   - €910,216 (28.6% del total familiar)
   - Perfil agresivo, horizonte 15 años, 52 años

2. Carrillo Bardo (Mamá):
   - €2,266,410 (71.4% del total familiar)
   - Perfil moderado, horizonte 10 años, 75 años

DISTRIBUCIÓN CONSOLIDADA:
- Renta Variable: 47.7% (objetivo 57%)
- Renta Fija: 31.2% (objetivo 30%)
- Oro/Oro Físico: 1.1% (objetivo 3%)
- Liquidez/Cripto: 20.0% (objetivo 10%)

ESTRUCTURA FISCAL FAMILIAR:
- Sociedad (Salva): 20.0% del patrimonio total
- Personal: 80.0% del patrimonio total

LIQUIDEZ TOTAL DISPONIBLE:
- Salva: €377k para inversión
- Mamá: €704k para inversión
- TOTAL: €1,081k (34% del patrimonio)

PLAN CONSOLIDADO 2026:
- Compras totales planificadas: €1,000k
- Fases: Enero (Cores), Febrero (Alpha), Marzo (Completar)
- Estrategias diferenciadas:
  * Salva: Alta convicción (Viking, Amgen, GEV)
  * Mamá: Conservador con alpha (Roche, Lilly, Utilities)

ESTRATEGIA FAMILIAR:
- Balanceo intergeneracional optimizado
- Salva: crecimiento agresivo con alpha
- Mamá: preservación + alpha controlado
- Sincronización en Eli Lilly (ambos)
- Tema nuclear 360º (Uranium + Operadores)`

}

export async function POST(request: Request) {
  try {
    const body = await request.json()

    // Validate request
    const validation = validateRequest(ChatRequestSchema, body)
    if (!validation.success) {
      return NextResponse.json(
        { error: validation.error },
        { status: 400 }
      )
    }

    const { message, history, portfolioId } = validation.data

    // Get portfolio-specific context
    const portfolioContext = PORTFOLIO_CONTEXTS[portfolioId]

    const systemContext = `Eres FinRobot, un asesor financiero personal especializado para la familia Carrillo-Bardo.

${portfolioContext}

TU ROL:
1. Analiza preguntas sobre mercado, activos, estrategia
2. Proporciona recomendaciones basadas en el perfil específico
3. Considera la estructura fiscal adecuada
4. Sé conciso pero fundamentado
5. Usa datos de mercado cuando sea relevante

IMPORTANTE:
- Responde en español
- Sé específico con números
- Considera el timing de las inversiones
- Ten en cuenta la fiscalidad española
- Adapta las recomendaciones al perfil de riesgo del patrimonio consultado

${portfolioId === 'salva' ? 'Este patrimonio es más agresivo y busca crecimiento a largo plazo.' :
  portfolioId === 'madre' ? 'Este patrimonio es conservador, prioriza preservación de capital y generación de ingresos estables.' :
  'Este es el patrimonio consolidado. Proporciona análisis que considere ambos perfiles de inversión.'}

Responde de forma clara y accionable.`

    const messages = [
      { role: 'system' as const, content: systemContext },
      ...history.map((msg: any) => ({
        role: msg.role,
        content: msg.content
      })),
      { role: 'user' as const, content: message }
    ]

    const completion = await getOpenAI().chat.completions.create({
      model: 'gpt-4o',
      messages,
      temperature: 0.3,
      max_tokens: 1000,
    })

    const response = completion.choices[0]?.message?.content || 'Lo siento, no pude generar una respuesta.'

    return NextResponse.json({ response })

  } catch (error) {
    console.error('Error in chat API:', error)
    const message = error instanceof Error ? error.message : 'Unknown error'
    return NextResponse.json(
      { error: 'Error processing query', details: message },
      { status: 500 }
    )
  }
}
