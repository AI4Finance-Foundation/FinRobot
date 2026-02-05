'use client'

import { TrendingUp, TrendingDown, Wallet, PieChart as PieChartIcon, AlertCircle } from 'lucide-react'
import { Portfolio } from '@/lib/portfolioData'
import { DistributionPieChartCompact } from './DistributionPieChart'

type Props = {
  portfolio: Portfolio
}

export default function DashboardMulti({ portfolio }: Props) {
  return (
    <div className="space-y-6">
      {/* Header con titular */}
      <div className="bg-gradient-to-r from-blue-50 to-purple-50 rounded-lg p-4 border border-blue-100">
        <h2 className="text-2xl font-bold text-slate-800">{portfolio.nombre}</h2>
        <p className="text-sm text-slate-600">{portfolio.titular}</p>
      </div>

      {/* Métricas principales */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <MetricCard
          title="Valor Total"
          value={`€${portfolio.valor_total.toLocaleString()}`}
          change={`+${portfolio.pnl_pct.toFixed(1)}%`}
          positive={portfolio.pnl > 0}
          icon={<Wallet className="w-6 h-6" />}
        />

        <MetricCard
          title="P&L"
          value={`€${portfolio.pnl.toLocaleString()}`}
          change={portfolio.pnl >= 0 ? "Ganancia" : "Pérdida"}
          positive={portfolio.pnl >= 0}
          icon={<TrendingUp className="w-6 h-6" />}
        />

        <MetricCard
          title="Posiciones"
          value={portfolio.posiciones_count.toString()}
          icon={<PieChartIcon className="w-6 h-6" />}
        />

        <MetricCard
          title="Rebalanceo"
          value={portfolio.necesita_rebalanceo ? "Necesario" : "OK"}
          change={portfolio.necesita_rebalanceo ? "⚠️" : "✅"}
          icon={<TrendingDown className="w-6 h-6" />}
        />
      </div>

      {/* Estructura Fiscal */}
      {portfolio.id !== 'carrillo_familia' && (
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold mb-4">🏦 Estructura Fiscal</h3>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="text-sm text-slate-600">Sociedad</div>
              <div className="text-2xl font-bold text-blue-600">
                {portfolio.estructura_fiscal.sociedad_pct.toFixed(0)}%
              </div>
              {portfolio.estructura_fiscal.broker_sociedad && (
                <div className="text-xs text-slate-500">
                  {portfolio.estructura_fiscal.broker_sociedad}
                </div>
              )}
            </div>
            <div>
              <div className="text-sm text-slate-600">Personal</div>
              <div className="text-2xl font-bold text-purple-600">
                {portfolio.estructura_fiscal.personal_pct.toFixed(0)}%
              </div>
              {portfolio.estructura_fiscal.broker_personal && (
                <div className="text-xs text-slate-500">
                  {portfolio.estructura_fiscal.broker_personal}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Distribución */}
      <div className="bg-white rounded-lg shadow p-6">
        <h2 className="text-xl font-bold mb-4">📊 Distribución Actual vs Objetivo</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Pie Chart */}
          <div className="flex items-center justify-center">
            <DistributionPieChartCompact distribution={portfolio.distribucion} />
          </div>

          {/* Progress Bars */}
          <div className="md:col-span-2 space-y-4">
            {Object.entries(portfolio.distribucion).map(([key, data]) => {
              if (!data || data.valor === 0) return null

              const categoryNames: Record<string, string> = {
                renta_variable: 'Renta Variable',
                renta_fija: 'Renta Fija',
                oro: 'Oro',
                liquidez: 'Liquidez'
              }

              return (
                <div key={key}>
                  <div className="flex justify-between mb-2">
                    <span className="font-medium">{categoryNames[key] || key}</span>
                    <span className="text-sm text-slate-600">
                      Actual: {data.actual.toFixed(1)}% |
                      Objetivo: {data.objetivo.toFixed(1)}% |
                      €{data.valor.toLocaleString()}
                    </span>
                  </div>
                  <div className="w-full bg-slate-200 rounded-full h-3">
                    <div
                      className={`h-3 rounded-full transition-all ${
                        data.actual > data.objetivo ? 'bg-yellow-500' :
                        data.actual < data.objetivo ? 'bg-orange-500' :
                        'bg-green-500'
                      }`}
                      style={{ width: `${Math.min(data.actual, 100)}%` }}
                    />
                  </div>
                  <div className="text-xs text-slate-500 mt-1">
                    Desviación: {(data.actual - data.objetivo).toFixed(1)}%
                    {Math.abs(data.actual - data.objetivo) > 5 && ' ⚠️'}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {/* Perfil del Inversor */}
      {portfolio.id !== 'carrillo_familia' && (
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold mb-4">👤 Perfil del Inversor</h3>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <div className="text-sm text-slate-600">Edad</div>
              <div className="text-xl font-bold">{portfolio.perfil.edad} años</div>
            </div>
            <div>
              <div className="text-sm text-slate-600">Horizonte</div>
              <div className="text-xl font-bold">{portfolio.perfil.horizonte_anos} años</div>
            </div>
            <div>
              <div className="text-sm text-slate-600">Riesgo</div>
              <div className="text-xl font-bold capitalize">
                {portfolio.perfil.tolerancia_riesgo.replace('_', ' ')}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Alertas */}
      {portfolio.necesita_rebalanceo && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 flex items-start space-x-3">
          <AlertCircle className="w-5 h-5 text-yellow-600 mt-0.5" />
          <div>
            <h3 className="font-semibold text-yellow-900 mb-1">⚠️ Rebalanceo Requerido</h3>
            <p className="text-yellow-800 text-sm">
              Este patrimonio necesita rebalanceo. Usa el chat de FinRobot para obtener
              recomendaciones personalizadas.
            </p>
          </div>
        </div>
      )}

      {/* Especial para consolidado */}
      {portfolio.id === 'carrillo_familia' && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4">
          <h3 className="font-semibold text-green-900 mb-2">👨‍👩‍👦 Vista Consolidada Familia</h3>
          <p className="text-green-800 text-sm">
            Este es el patrimonio total combinado de Salvador Carrillo y Madre Carrillo.
            Para ver detalles específicos, selecciona un patrimonio individual.
          </p>
        </div>
      )}
    </div>
  )
}

function MetricCard({
  title,
  value,
  change,
  positive,
  icon
}: {
  title: string
  value: string
  change?: string
  positive?: boolean
  icon: React.ReactNode
}) {
  return (
    <div className="bg-white rounded-lg shadow p-6 hover:shadow-lg transition-shadow">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium text-slate-600">{title}</span>
        <div className="text-slate-400">{icon}</div>
      </div>
      <div className="text-2xl font-bold text-slate-900">{value}</div>
      {change && (
        <div className={`text-sm font-medium mt-1 ${
          positive === true ? 'text-green-600' :
          positive === false ? 'text-red-600' :
          'text-slate-600'
        }`}>
          {change}
        </div>
      )}
    </div>
  )
}
