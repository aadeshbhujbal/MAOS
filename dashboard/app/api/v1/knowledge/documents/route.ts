import { NextResponse } from "next/server";
import { MOCK_DOCUMENTS } from "@/app/api/mock/data";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const ns = searchParams.get("namespace");
  const docs = ns ? MOCK_DOCUMENTS.filter((d) => d.namespace === ns) : MOCK_DOCUMENTS;

  return NextResponse.json({
    items: docs,
    total_count: docs.length,
    offset: 0,
    limit: 50,
  });
}
