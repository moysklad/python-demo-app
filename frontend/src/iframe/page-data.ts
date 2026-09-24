// [feature:loyalty] программа лояльности: данные вкладки приходят из модуля app/loyalty.
import type { LoyaltyConnectionState } from "../loyalty/types";

/** Состояние решения для карточки статуса; в таком же виде его возвращает POST /utils/update-settings. */
export type AppStatusView = {
  /** Цвет бейджа статуса (Badge из кита): зеленый — готово, оранжевый — нужны действия. */
  badge: "green" | "orange";
  title: string;
  showDetails: boolean;
  infoMessage?: string;
  store?: string;
};

/**
 * Данные страницы основного iframe: поле pageData в ответе POST /entry/user-context,
 * формирует их app/services/entry.py.
 */
export type IframePageData = {
  accountId: string;
  uid: string;
  fio: string;
  isAdmin: boolean;
  contextNonce: string;
  appVersion: string;
  infoMessage?: string;
  store?: string;
  storesValues: string[];
  status: AppStatusView;
  // [feature:loyalty] программа лояльности
  loyalty: LoyaltyConnectionState;
  defaultLoyaltyProviderUrl: string;
};
