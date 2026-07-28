import { NextResponse } from "next/server";
import { MOCK_MCP_SERVERS } from "@/app/api/mock/data";

export async function GET() {
  return NextResponse.json(MOCK_MCP_SERVERS);
}
