import { useHealthz } from '@/lib/queries';

const REPO_URL = 'https://github.com/owine/youth-activity-scheduler';

export function Footer() {
  const { data } = useHealthz();
  if (!data) return null;
  const shortSha = data.git_sha === 'unknown' ? null : data.git_sha.slice(0, 7);
  return (
    <footer className="border-t border-border mt-8 px-4 py-3 text-xs text-muted-foreground">
      <div className="container max-w-5xl flex items-center justify-between">
        <span>
          YAS v{data.version}
          {shortSha && (
            <>
              {' · '}
              <a
                href={`${REPO_URL}/commit/${data.git_sha}`}
                target="_blank"
                rel="noopener noreferrer"
                className="font-mono hover:text-foreground hover:underline"
                title={data.git_sha}
              >
                {shortSha}
              </a>
            </>
          )}
        </span>
      </div>
    </footer>
  );
}
