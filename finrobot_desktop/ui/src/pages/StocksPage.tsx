import { useParams } from "react-router-dom";

export function StocksPage() {
  const { ticker } = useParams();
  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold">
        Stocks{ticker ? ` — ${ticker.toUpperCase()}` : ""}
      </h1>
      <p className="mt-2 text-sm text-neutral-500">(待 Stocks page agent 填充)</p>
    </div>
  );
}
