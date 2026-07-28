import { NextResponse } from "next/server";
import { MOCK_COSTS } from "@/app/api/mock/data";

export async function GET() {
  const totalTokens = MOCK_COSTS.reduce((sum, c) => sum + c.tokens, 0);
  const totalCost = MOCK_COSTS.reduce((sum, c) => sum + c.cost_usd, 0);

  return NextResponse.json({
    total_tokens: totalTokens,
    total_cost_usd: Math.round(totalCost * 100) / 100,
    by_provider: [
      { dimension: "provider", key: "Anthropic", total_tokens: 55200, total_cost_usd: 1.99 },
      { dimension: "provider", key: "OpenAI", total_tokens: 22000, total_cost_usd: 0.88 },
      { dimension: "provider", key: "Bedrock", total_tokens: 3000, total_cost_usd: 0.11 },
      { dimension: "provider", key: "Vertex", total_tokens: 8200, total_cost_usd: 0.16 },
    ],
    by_agent: [
      { dimension: "agent_id", key: "agent-backend-001", total_tokens: 38700, total_cost_usd: 1.40 },
      { dimension: "agent_id", key: "agent-web-001", total_tokens: 22000, total_cost_usd: 0.88 },
      { dimension: "agent_id", key: "agent-backend-002", total_tokens: 9800, total_cost_usd: 0.35 },
      { dimension: "agent_id", key: "agent-mobile-001", total_tokens: 6700, total_cost_usd: 0.24 },
      { dimension: "agent_id", key: "agent-devops-001", total_tokens: 8200, total_cost_usd: 0.16 },
    ],
    by_tenant: [
      { dimension: "tenant_id", key: "tenant-alpha", total_tokens: 78700, total_cost_usd: 2.79 },
      { dimension: "tenant_id", key: "tenant-beta", total_tokens: 6700, total_cost_usd: 0.24 },
    ],
  });
}
