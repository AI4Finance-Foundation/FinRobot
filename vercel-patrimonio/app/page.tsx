'use client'

import { useState } from 'react'
import { MessageSquare, LayoutDashboard, FileText, Calendar, TrendingUp, Settings, Shield } from 'lucide-react'
import DashboardMulti from '@/components/DashboardMulti'
import RiskAnalysis from '@/components/RiskAnalysis'
import ChatPanel from '@/components/ChatPanel'
import PortfolioSelector from '@/components/PortfolioSelector'
import InvestmentPlan from '@/components/InvestmentPlan'
import PerformanceTrackerEnhanced from '@/components/PerformanceTrackerEnhanced'
import PortfolioDataSetup from '@/components/PortfolioDataSetup'
import { ALL_PORTFOLIOS, PortfolioId } from '@/lib/portfolioData'
import { ALL_OPERATIONS } from '@/lib/portfolioPlans'

export default function Home() {
  const [activeTab, setActiveTab] = useState<'dashboard' | 'risk' | 'plan' | 'performance' | 'setup' | 'chat' | 'docs'>('dashboard')
  const [selectedPortfolio, setSelectedPortfolio] = useState<PortfolioId>('salva')

  const currentPortfolio = ALL_PORTFOLIOS[selectedPortfolio]
  const operations = selectedPortfolio === 'consolidado'
    ? { ventas: [], compras: [] }
    : ALL_OPERATIONS[selectedPortfolio as 'salva' | 'madre']

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100">
      {/* Selector de Patrimonio */}
      <PortfolioSelector
        selectedPortfolio={selectedPortfolio}
        onSelect={setSelectedPortfolio}
      />

      {/* Navigation Tabs */}
      <nav className="bg-white border-b border-slate-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex space-x-8">
            <TabButton
              active={activeTab === 'dashboard'}
              onClick={() => setActiveTab('dashboard')}
              icon={<LayoutDashboard className="w-4 h-4" />}
              label="Dashboard"
            />

            <TabButton
              active={activeTab === 'risk'}
              onClick={() => setActiveTab('risk')}
              icon={<Shield className="w-4 h-4" />}
              label="Risk Analysis"
            />

            <TabButton
              active={activeTab === 'plan'}
              onClick={() => setActiveTab('plan')}
              icon={<Calendar className="w-4 h-4" />}
              label="Plan de Inversión"
              badge={selectedPortfolio !== 'consolidado' ? operations.compras.length : undefined}
            />

            <TabButton
              active={activeTab === 'performance'}
              onClick={() => setActiveTab('performance')}
              icon={<TrendingUp className="w-4 h-4" />}
              label="P&L Tracking"
            />

            <TabButton
              active={activeTab === 'setup'}
              onClick={() => setActiveTab('setup')}
              icon={<Settings className="w-4 h-4" />}
              label="Configuración"
            />

            <TabButton
              active={activeTab === 'chat'}
              onClick={() => setActiveTab('chat')}
              icon={<MessageSquare className="w-4 h-4" />}
              label="Chat FinRobot"
            />

            <TabButton
              active={activeTab === 'docs'}
              onClick={() => setActiveTab('docs')}
              icon={<FileText className="w-4 h-4" />}
              label="Documentación"
            />
          </div>
        </div>
      </nav>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {activeTab === 'dashboard' && (
          <DashboardMulti portfolio={currentPortfolio} />
        )}

        {activeTab === 'risk' && (
          <RiskAnalysis portfolioId={selectedPortfolio} />
        )}

        {activeTab === 'plan' && (
          selectedPortfolio === 'consolidado' ? (
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-6">
              <h3 className="font-semibold text-yellow-900 mb-2">ℹ️ Vista Consolidada</h3>
              <p className="text-yellow-800">
                El plan de inversión detallado está disponible para cada patrimonio individual.
                Selecciona "Salva" o "Madre" para ver los planes específicos.
              </p>
            </div>
          ) : (
            <InvestmentPlan
              ventas={operations.ventas}
              compras={operations.compras}
              portfolioName={currentPortfolio.nombre}
            />
          )
        )}

        {activeTab === 'performance' && (
          <PerformanceTrackerEnhanced />
        )}

        {activeTab === 'setup' && (
          <PortfolioDataSetup onComplete={(data) => {
            console.log('Datos guardados:', data)
            setActiveTab('performance')
          }} />
        )}

        {activeTab === 'chat' && (
          <ChatPanel selectedPortfolio={selectedPortfolio} />
        )}

        {activeTab === 'docs' && (
          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-xl font-bold mb-4">📄 Documentación Guardada</h2>
            <p className="text-slate-600 mb-4">
              Aquí se guardarán automáticamente los análisis y conversaciones importantes
              para el patrimonio: <strong>{currentPortfolio.nombre}</strong>
            </p>

            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
              <h3 className="font-semibold text-blue-900 mb-2">💡 Próximamente</h3>
              <ul className="text-blue-800 text-sm space-y-1">
                <li>• Historial de conversaciones por patrimonio</li>
                <li>• Análisis guardados con etiquetas</li>
                <li>• Exportación a PDF de reportes</li>
                <li>• Comparativas históricas</li>
              </ul>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}

function TabButton({
  active,
  onClick,
  icon,
  label,
  badge
}: {
  active: boolean
  onClick: () => void
  icon: React.ReactNode
  label: string
  badge?: number
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center space-x-2 px-3 py-4 border-b-2 font-medium text-sm transition-colors relative ${
        active
          ? 'border-blue-500 text-blue-600'
          : 'border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300'
      }`}
    >
      {icon}
      <span>{label}</span>
      {badge !== undefined && badge > 0 && (
        <span className="absolute -top-1 -right-1 bg-red-500 text-white text-xs font-bold rounded-full w-5 h-5 flex items-center justify-center">
          {badge}
        </span>
      )}
    </button>
  )
}
