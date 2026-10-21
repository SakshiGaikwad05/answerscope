"use client";

import type { LocalProfileInput, Project } from "@/lib/api";

export interface LocalDraft {
  city: string;
  region: string;
  country: string;
  service_area: string;
  address: string;
  phone: string;
  opening_hours: string;
  services: string; // one per line
  profile_urls: string; // one per line
}

export const EMPTY_LOCAL: LocalDraft = {
  city: "", region: "", country: "", service_area: "", address: "", phone: "", opening_hours: "", services: "", profile_urls: "",
};

export function localDraftFrom(p: Project): LocalDraft {
  return {
    city: p.city ?? "", region: p.region ?? "", country: p.country ?? "", service_area: p.service_area ?? "",
    address: p.address ?? "", phone: p.phone ?? "", opening_hours: p.opening_hours ?? "",
    services: (p.services ?? []).join("\n"), profile_urls: (p.profile_urls ?? []).join("\n"),
  };
}

const lines = (v: string) => v.split(/\n|,(?![^(]*\))/).map((s) => s.trim()).filter(Boolean);

export function localPayload(d: LocalDraft): LocalProfileInput {
  const t = (v: string) => v.trim() || null;
  return {
    city: t(d.city), region: t(d.region), country: t(d.country)?.toUpperCase() ?? null, service_area: t(d.service_area),
    address: t(d.address), phone: t(d.phone), opening_hours: t(d.opening_hours),
    services: lines(d.services), profile_urls: d.profile_urls.split("\n").map((s) => s.trim()).filter(Boolean),
  };
}

function Field({ id, label, hint, value, onChange, placeholder, maxLength = 300, textarea }: {
  id: string; label: string; hint?: string; value: string; onChange: (v: string) => void; placeholder?: string;
  maxLength?: number; textarea?: boolean;
}) {
  const cls = "mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm";
  return (
    <div>
      <label htmlFor={id} className="text-sm font-medium text-slate-800">{label}</label>
      {textarea ? (
        <textarea id={id} rows={3} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className={cls} aria-describedby={hint ? `${id}-hint` : undefined} />
      ) : (
        <input id={id} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} maxLength={maxLength} className={cls} aria-describedby={hint ? `${id}-hint` : undefined} />
      )}
      {hint && <p id={`${id}-hint`} className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

export function LocalProfileFields({ value, onChange }: { value: LocalDraft; onChange: (v: LocalDraft) => void }) {
  const set = (k: keyof LocalDraft) => (v: string) => onChange({ ...value, [k]: v });
  return (
    <fieldset className="space-y-4">
      <legend className="text-sm font-semibold text-slate-900">Business location & details <span className="font-normal text-slate-500">(recommended for local businesses)</span></legend>
      <p className="text-xs text-slate-500">
        Used to ask location-specific questions, check that your website shows these details, and draft accurate structured data. Only
        the details you enter here, or ones found on your site, are ever used. Nothing is made up.
      </p>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field id="city" label="Town / city" value={value.city} onChange={set("city")} placeholder="Akola" maxLength={120} />
        <Field id="region" label="State / region" value={value.region} onChange={set("region")} placeholder="Maharashtra" maxLength={120} />
        <Field id="country" label="Country code" value={value.country} onChange={set("country")} placeholder="IN" maxLength={2} hint="2 letters, e.g. IN, US" />
      </div>
      <Field id="service_area" label="Service area" value={value.service_area} onChange={set("service_area")} placeholder="Akola district, Washim" />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field id="address" label="Street address" value={value.address} onChange={set("address")} placeholder="Station Road, Akola 444001" maxLength={500} />
        <Field id="phone" label="Phone" value={value.phone} onChange={set("phone")} placeholder="+91 98765 43210" maxLength={40} />
      </div>
      <Field id="opening_hours" label="Opening hours" value={value.opening_hours} onChange={set("opening_hours")} placeholder="Mo-Sa 09:00-19:00"
             hint="Use the format Mo-Sa 09:00-19:00 so it can go straight into structured data." />
      <Field id="services" label="Main services or products" value={value.services} onChange={set("services")} textarea placeholder={"Seeds\nFertilizers\nCrop advice"} hint="One per line." />
      <Field id="profile_urls" label="Official profile links" value={value.profile_urls} onChange={set("profile_urls")} textarea
             placeholder={"https://g.page/r/your-google-business-profile\nhttps://instagram.com/yourbusiness"}
             hint="Google Business Profile, social pages, directory listings. One per line." />
    </fieldset>
  );
}
