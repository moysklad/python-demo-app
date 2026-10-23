import type { AppStatusView } from "../iframe/page-data";
// [feature:scenario] действия в сценариях: журнал приходит из модуля app/scenario.
import type { ScenarioJournalData } from "../scenario/types";

/**
 * Данные окна чатов: поле pageData в ответе POST /entry/user-context с page: "chat",
 * формирует их app/services/entry.py.
 */
export type ChatPageData = ScenarioJournalData & {
  accountId: string;
  uid: string;
  fio: string;
  isAdmin: boolean;
  contextNonce: string;
  appVersion: string;
  status: AppStatusView;
};
