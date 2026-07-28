import { NextResponse } from "next/server";
import { MOCK_DOCUMENTS } from "@/app/api/mock/data";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const q = (searchParams.get("q") ?? "").toLowerCase();
  const ns = searchParams.get("namespace");

  const filtered = MOCK_DOCUMENTS.filter((d) => {
    if (ns && d.namespace !== ns) return false;
    return d.filename.toLowerCase().includes(q);
  });

  return NextResponse.json(
    filtered.map((doc, i) => ({
      document: doc,
      score: 0.95 - i * 0.1,
      snippet: `...matched content from ${doc.filename}...`,
    }))
  );
}
