import { NextResponse } from "next/server";
import { MOCK_AGENTS } from "@/app/api/mock/data";

export async function GET() {
  return NextResponse.json(MOCK_AGENTS);
}
