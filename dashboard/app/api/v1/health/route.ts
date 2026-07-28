import { NextResponse } from "next/server";
import { MOCK_SERVICES } from "@/app/api/mock/data";

export async function GET() {
  return NextResponse.json({
    overall: "degraded",
    services: MOCK_SERVICES,
    metrics: {
      active_ws_connections: 3,
      message_queue_depth: 12,
      tasks_per_minute: 4.2,
    },
  });
}
