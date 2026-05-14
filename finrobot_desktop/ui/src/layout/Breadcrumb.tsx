// Phase 1: hardcoded breadcrumb. Phase 3 will bind to activeTab.
export function Breadcrumb(): React.ReactElement {
  return (
    <div className="breadcrumb">
      <span className="seg">FinAgent</span>
      <span className="sep">›</span>
      <span className="seg">workspace</span>
      <span className="sep">›</span>
      <span className="seg">工作台首页</span>
    </div>
  )
}
