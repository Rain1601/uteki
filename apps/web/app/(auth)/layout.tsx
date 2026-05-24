/**
 * Bare layout for /login, /register, and /oauth callbacks.
 * No sidebar — keeps focus on the auth form and avoids the layout shift
 * that would happen if the app shell briefly mounted then unmounted.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative min-h-screen bg-[var(--bg)] paper-grain">
      {children}
    </div>
  );
}
