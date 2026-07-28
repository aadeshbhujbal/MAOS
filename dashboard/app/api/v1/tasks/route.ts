import { NextResponse } from "next/server";
import { MOCK_TASKS } from "@/app/api/mock/data";

export async function GET() {
  return NextResponse.json({
    items: MOCK_TASKS,
    total_count: MOCK_TASKS.length,
    offset: 0,
    limit: 50,
  });
}
