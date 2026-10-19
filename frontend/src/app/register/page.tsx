import { Suspense } from "react";

import { AuthForm } from "@/components/AuthForm";
import { Loading } from "@/components/ui";

export default function RegisterPage() {
  return (
    <Suspense fallback={<Loading />}>
      <AuthForm mode="register" />
    </Suspense>
  );
}
