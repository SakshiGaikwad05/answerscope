import { Suspense } from "react";

import { AuthForm } from "@/components/AuthForm";
import { Loading } from "@/components/ui";

export default function LoginPage() {
  return (
    <Suspense fallback={<Loading />}>
      <AuthForm mode="login" />
    </Suspense>
  );
}
