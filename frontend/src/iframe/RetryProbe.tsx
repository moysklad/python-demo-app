import { type FormEvent, useState } from "react";
import { Banner } from "@moysklad/uikit/components/Banner";
import { Button, ButtonVariants } from "@moysklad/uikit/components/Button";
import { Input } from "@moysklad/uikit/components/Input";
import { Text } from "@moysklad/uikit/components/Text";
import { VStack } from "@moysklad/uikit/components/VStack";

const STORES_URL = "/utils/stores";
const MAX_REQUEST_COUNT = 1000;
const STAGGER_MS = 30;

type StoresResponse = { success?: boolean; retries?: number };
type Progress = { total: number; completed: number; successful: number; failed: number; retries: number };

/**
 * Ручная проверка ретраев JSON API: выбранное количество запросов списка складов уходит почти одновременно,
 * backend (POST /utils/stores) повторяет их по заголовку X-Lognex-Retry-After и возвращает число повторов.
 */
export function RetryProbe({ contextNonce }: { contextNonce: string }) {
  const [requestCount, setRequestCount] = useState("50");
  const [isRunning, setRunning] = useState(false);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const total = Number(requestCount);

    if (!Number.isInteger(total) || total < 1 || total > MAX_REQUEST_COUNT) {
      setError(`Количество запросов должно быть от 1 до ${MAX_REQUEST_COUNT}`);
      return;
    }

    setError(null);
    setRunning(true);
    const current: Progress = { total, completed: 0, successful: 0, failed: 0, retries: 0 };
    setProgress({ ...current });

    await Promise.all(
      Array.from({ length: total }, async (_, index) => {
        await new Promise((resolve) => window.setTimeout(resolve, index * STAGGER_MS));

        try {
          const response = await fetch(STORES_URL, {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ contextNonce })
          });
          const contentType = response.headers.get("content-type") || "";
          const payload = (contentType.includes("application/json") ? await response.json() : null) as StoresResponse | null;

          current.retries += Number.isInteger(payload?.retries) ? Number(payload?.retries) : 0;
          if (response.ok && payload?.success) {
            current.successful += 1;
          } else {
            current.failed += 1;
          }
        } catch {
          current.failed += 1;
        } finally {
          current.completed += 1;
          setProgress({ ...current });
        }
      })
    );

    setRunning(false);
  }

  const summary =
    progress &&
    `Выполнено: ${progress.completed} из ${progress.total}. Успешно: ${progress.successful}, ошибок: ${progress.failed}, ретраев: ${progress.retries}.`;

  return (
    <form onSubmit={run}>
      <VStack size="s12">
        <Text.H3>Проверка ретраев</Text.H3>
        <Text.Body>
          Выполнится выбранное количество запросов списка складов и покажет срабатывания ретраев по заголовку{" "}
          <code>X-Lognex-Retry-After</code>.
        </Text.Body>
        <Input
          name="requestCount"
          label="Количество запросов"
          type="number"
          min={1}
          max={MAX_REQUEST_COUNT}
          value={requestCount}
          onChange={(event) => setRequestCount(event.target.value)}
        />
        <div>
          <Button type="submit" variant={ButtonVariants.SECONDARY} isLoading={isRunning}>
            Запустить проверку
          </Button>
        </div>
        {error && <Banner type="warning" title={error} />}
        {summary && (
          <Banner type={isRunning || progress.failed === 0 ? "info" : "warning"} title={summary} />
        )}
      </VStack>
    </form>
  );
}
