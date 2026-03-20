import { useState } from 'react';

const PROFILES = [
  {
    id: 'marcus',
    name: 'Marcus T.',
    tag: 'Disabled Veteran',
    detail: 'Army · IRRRL candidate',
    accent: '#C8102E',
    fields: [
      { label: 'Service',       value: 'U.S. Army, 8 yrs, honorably discharged (2018)' },
      { label: 'Disability',    value: '10% service-connected — funding fee exempt' },
      { label: 'Loan',          value: 'Existing VA loan — IRRRL candidate' },
      { label: 'Balance',       value: '$320,000' },
      { label: 'Current rate',  value: '6.8%' },
      { label: 'New rate',      value: '6.1%' },
      { label: 'Remaining',     value: '27 years' },
      { label: 'Appt pref',     value: 'Thursday @ 2:00 PM' },
    ],
  },
  {
    id: 'sarah',
    name: 'Sarah K.',
    tag: 'First-time buyer',
    detail: 'Navy · Purchase loan',
    accent: '#1D4ED8',
    fields: [
      { label: 'Service',       value: 'U.S. Navy, 4 yrs active duty, discharged (2021)' },
      { label: 'Disability',    value: 'None' },
      { label: 'Loan',          value: 'First VA loan — home purchase' },
      { label: 'Purchase price', value: '$350,000' },
      { label: 'Rate quoted',   value: '6.25%' },
      { label: 'Term',          value: '30 years' },
      { label: 'Funding fee',   value: 'Standard (not exempt)' },
      { label: 'Appt pref',     value: 'Monday @ 10:00 AM' },
    ],
  },
  {
    id: 'james',
    name: 'Lt. James R.',
    tag: 'Active duty',
    detail: 'Army · Second use',
    accent: '#4F46E5',
    fields: [
      { label: 'Service',       value: 'U.S. Army, active duty (currently deployed — OCONUS)' },
      { label: 'Disability',    value: 'None' },
      { label: 'Loan',          value: 'Second VA use — entitlement restored' },
      { label: 'Balance',       value: '$400,000' },
      { label: 'Current rate',  value: '7.1%' },
      { label: 'New rate',      value: '6.3%' },
      { label: 'Remaining',     value: '29 years' },
      { label: 'Appt pref',     value: 'Friday @ 3:00 PM' },
    ],
  },
];

export default function BorrowerProfile({ profileId, onChange }) {
  const [expanded, setExpanded] = useState(true);
  const active = PROFILES.find(p => p.id === profileId) ?? null;

  return (
    <div className="flex-shrink-0" style={{ borderBottom: '1px solid #E5E2DC' }}>

      {/* ── Pill row ── */}
      <div
        className="flex items-center gap-3 px-4 py-2 overflow-x-auto"
        style={{ background: '#F8F7F4' }}
      >
        <span
          className="text-xs font-semibold uppercase flex-shrink-0"
          style={{ color: '#6B7280', letterSpacing: '0.05em' }}
        >
          Borrower:
        </span>

        {/* No profile */}
        <button
          onClick={() => { onChange(null); setExpanded(true); }}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full flex-shrink-0 transition-all border-none cursor-pointer"
          style={{
            background: profileId === null ? '#002244' : 'white',
            color:      profileId === null ? 'white'   : '#6B7280',
            border:     profileId === null ? '1.5px solid #002244' : '1.5px solid #D1D5DB',
            fontFamily: 'inherit',
          }}
        >
          <span style={{ fontSize: '10px' }}>◯</span>
          No profile
        </button>

        {/* Profile pills */}
        {PROFILES.map(p => {
          const isActive = profileId === p.id;
          return (
            <button
              key={p.id}
              onClick={() => {
                if (isActive) { onChange(null); } else { onChange(p.id); setExpanded(true); }
              }}
              className="flex items-center gap-2 text-xs px-3 py-1.5 rounded-full flex-shrink-0 transition-all border-none cursor-pointer"
              style={{
                background: isActive ? p.accent : 'white',
                color:      isActive ? 'white'  : '#374151',
                border:     isActive ? `1.5px solid ${p.accent}` : '1.5px solid #D1D5DB',
                fontFamily: 'inherit',
              }}
            >
              <span className="font-semibold">{p.name}</span>
              <span style={{ opacity: isActive ? 0.8 : 0.5 }}>·</span>
              <span style={{ opacity: isActive ? 0.85 : 0.65 }}>{p.tag}</span>
            </button>
          );
        })}

        {/* Expand/collapse toggle — only shown when a profile is active */}
        {active && (
          <button
            onClick={() => setExpanded(v => !v)}
            className="ml-auto flex items-center gap-1 text-xs flex-shrink-0 border-none cursor-pointer"
            style={{
              background: 'transparent',
              color: '#9CA3AF',
              fontFamily: 'inherit',
            }}
          >
            {expanded ? '▲ hide' : '▼ details'}
          </button>
        )}
      </div>

      {/* ── Detail card ── */}
      {active && expanded && (
        <div
          className="px-4 py-2.5"
          style={{ background: '#FAFAF9', borderTop: '1px solid #F0EDE8' }}
        >
          <div className="flex flex-wrap gap-x-6 gap-y-1">
            {active.fields.map(f => (
              <div key={f.label} className="flex items-baseline gap-1.5 text-xs">
                <span
                  className="font-semibold uppercase flex-shrink-0"
                  style={{ color: active.accent, letterSpacing: '0.04em', fontSize: '10px' }}
                >
                  {f.label}
                </span>
                <span style={{ color: '#374151' }}>{f.value}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
