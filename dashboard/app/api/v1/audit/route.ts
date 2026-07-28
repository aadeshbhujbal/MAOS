import { NextResponse } from "next/server";
import { MOCK_AUDIT } from "@/app/api/mock/data";

export async function GET() {
  return NextResponse.json({
    items: MOCK_AUDIT,
    total_count: MOCK_AUDIT.length,
    offset: 0,
    limit: 50,
  });
}
