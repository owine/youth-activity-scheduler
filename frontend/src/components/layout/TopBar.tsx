import { Link } from '@tanstack/react-router';
import { Bell, Globe, LayoutGrid, Mail, Settings } from 'lucide-react';
import { KidSwitcher } from './KidSwitcher';
import { ThemeToggle } from './ThemeToggle';
import { useInboxSummary } from '@/lib/queries';
import { Badge } from '@/components/ui/badge';

export function TopBar() {
  const { data } = useInboxSummary();
  const alertCount = data?.alerts.length ?? 0;

  return (
    <header className="border-b border-border bg-background/95 backdrop-blur-sm px-4 py-2.5 flex items-center gap-4">
      <Link to="/" className="text-lg font-semibold">
        YAS
      </Link>
      <div className="flex-1">
        <KidSwitcher />
      </div>
      <Link
        to="/"
        className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <Bell className="h-4 w-4" /> Inbox
        {alertCount > 0 && (
          <Badge variant="destructive" className="ml-1 h-5 px-1.5 text-xs">
            {alertCount}
          </Badge>
        )}
      </Link>
      <Link
        to="/offerings"
        className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <LayoutGrid className="h-4 w-4" /> Offerings
      </Link>
      <Link
        to="/alerts"
        className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <Mail className="h-4 w-4" /> Alerts
      </Link>
      <Link
        to="/sites"
        className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <Globe className="h-4 w-4" /> Sites
      </Link>
      <Link
        to="/settings"
        className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <Settings className="h-4 w-4" /> Settings
      </Link>
      <ThemeToggle />
    </header>
  );
}
