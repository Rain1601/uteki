"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/** /admin redirects to the first sub-tab. The layout handles auth +
 *  navigation chrome; this page just decides the default landing. */
export default function AdminIndexPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/admin/users");
  }, [router]);
  return null;
}
