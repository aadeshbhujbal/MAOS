import { NextResponse } from "next/server";
import { MOCK_COSTS } from "@/app/api/mock/data";

export async function GET() {
  return NextResponse.json(MOCK_COSTS);
}
