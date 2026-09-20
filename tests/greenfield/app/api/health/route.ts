import { NextResponse } from "next/server";
import { db } from "@/lib/db";
export const runtime = "nodejs";
export async function GET() { return NextResponse.json({ ok: db.prepare("SELECT 1 AS ok").get() }); }
