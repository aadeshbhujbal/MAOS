import { NextResponse } from "next/server";
import { MOCK_NAMESPACES } from "@/app/api/mock/data";

export async function GET() {
  return NextResponse.json(MOCK_NAMESPACES);
}
