"use client";
import React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

/**
 * Copyright 2024 Example Corp. All rights reserved.
 * Licensed under the MIT License.
 */

export default function ProductPage() {
  const router = useRouter();
  return (
    <main>
      <h1>Product catalog</h1>
      <p>Browse widgets and gadgets with live inventory.</p>
      <button type="button" onClick={() => router.push("/cart")}>Go to cart</button>
      <Link href="/about">About</Link>
    </main>
  );
}
