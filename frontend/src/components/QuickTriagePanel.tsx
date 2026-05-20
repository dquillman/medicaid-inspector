import { useState } from "react";
import { Link } from "react-router-dom";

interface FlagLike {
  signal: string;
  flagged: boolean;
}

interface QuickTriagePanelProps {
  item: {
    npi: string;
    provider_name?: string;
    state?: string;
    risk_score: number;
    flags: FlagLike[];
    total_paid: number;
    total_claims: number;
    status: string;
    notes: string;
    assigned_to?: string | null;
  };
  onClose: () => void;
}

function fmtMoney(v: number): string {
  if (v >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `$${(v / 1e3).toFixed(0)}K`;
  return `$${v.toFixed(2)}`;
}

function titleCase(s: string): string {
  return s
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function QuickTriagePanel({ item, onClose }: QuickTriagePanelProps) {
  const [copied, setCopied] = useState(false);
  const { risk_score, flags: rawFlags, total_paid, total_claims } = item;
  const flagNames = rawFlags.filter(f => f.flagged).map(f => f.signal);

  // Risk level classification
  let riskEmoji: string;
  let riskLabel: string;
  let borderColor: string;
  let bgColor: string;

  if (risk_score >= 75) {
    riskEmoji = "\u{1F534}";
    riskLabel = "HIGH RISK";
    borderColor = "border-red-800";
    bgColor = "bg-red-950/30";
  } else if (risk_score >= 50) {
    riskEmoji = "\u{1F7E0}";
    riskLabel = "ELEVATED RISK";
    borderColor = "border-orange-800";
    bgColor = "bg-orange-950/30";
  } else if (risk_score >= 25) {
    riskEmoji = "\u{1F7E1}";
    riskLabel = "MODERATE RISK";
    borderColor = "border-yellow-800";
    bgColor = "bg-yellow-950/30";
  } else {
    riskEmoji = "\u{1F7E2}";
    riskLabel = "LOW RISK";
    borderColor = "border-green-800";
    bgColor = "bg-green-950/30";
  }

  // Line 1 — Risk assessment
  const line1 = `${riskEmoji} ${riskLabel} (score ${risk_score}) — ${flagNames.length} fraud signals triggered`;

  // Line 2 — Key signals
  const line2 =
    flagNames.length > 0
      ? `Signals: ${flagNames.map(titleCase).join(", ")}`
      : "No signals triggered.";

  // Line 3 — Recommendation
  let line3: string;
  if (risk_score >= 75) {
    line3 = `Recommend: Escalate for full investigation. ${fmtMoney(total_paid)} in claims across ${total_claims} services.`;
  } else if (risk_score >= 50) {
    line3 = `Recommend: Assign for detailed review. ${fmtMoney(total_paid)} in claims across ${total_claims} services.`;
  } else if (risk_score >= 25) {
    line3 = "Recommend: Monitor and reassess at next scan.";
  } else {
    line3 = "Recommend: No action needed at this time.";
  }

  const memoText = `${line1}\n${line2}\n${line3}`;

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(memoText);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback for older browsers
      const ta = document.createElement("textarea");
      ta.value = memoText;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }

  return (
    <tr>
      <td colSpan={12} className="p-0">
        <div
          className={`${bgColor} border-l-4 ${borderColor} px-5 py-3 mx-2 my-1 rounded-r`}
        >
          <div className="space-y-1 font-mono text-sm text-gray-200">
            <p>{line1}</p>
            <p>{line2}</p>
            <p>{line3}</p>
          </div>

          <div className="mt-3 flex items-center gap-2">
            <button
              onClick={handleCopy}
              className="rounded bg-gray-800 px-3 py-1 text-xs text-gray-300 hover:bg-gray-700 hover:text-white transition-colors"
            >
              {copied ? "Copied!" : "Copy Memo"}
            </button>
            <Link
              to={`/providers/${item.npi}`}
              className="rounded bg-gray-800 px-3 py-1 text-xs text-gray-300 hover:bg-gray-700 hover:text-white transition-colors"
            >
              View Provider
            </Link>
            <button
              onClick={onClose}
              className="rounded bg-gray-800 px-3 py-1 text-xs text-gray-300 hover:bg-gray-700 hover:text-white transition-colors"
            >
              Close
            </button>
          </div>
        </div>
      </td>
    </tr>
  );
}
