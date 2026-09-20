"""Скрипт 3: аудит тенанта -> CSV + список проблем в консоли.

Для каждого пользователя: отдел, должность, руководитель, вход разрешён или нет,
группы, зарегистрированные способы входа (есть ли MFA), последний вход.

Находит типовые проблемы:
  - нет MFA
  - нет отдела / должности / руководителя
  - заблокирован, но всё ещё состоит в группах (недоделанный офбординг)
  - внешние (гостевые) учётки

Нужно разрешение приложения UserAuthenticationMethod.Read.All (для MFA).
Последний вход (signInActivity) доступен только с лицензией Entra ID P1/P2 —
без неё скрипт не падает, а пишет "нужен P1".

Запуск: python audit.py
"""
import csv
from datetime import date

import requests

from graph import get_all, get_one

FIELDS = "id,displayName,userPrincipalName,jobTitle,department,accountEnabled,userType"

# Способы входа, которые считаются вторым фактором. Пароль и email — нет.
MFA_METHODS = {
    "#microsoft.graph.microsoftAuthenticatorAuthenticationMethod": "Authenticator",
    "#microsoft.graph.phoneAuthenticationMethod": "Телефон",
    "#microsoft.graph.fido2AuthenticationMethod": "FIDO2-ключ",
    "#microsoft.graph.softwareOathAuthenticationMethod": "OTP-приложение",
    "#microsoft.graph.windowsHelloForBusinessAuthenticationMethod": "Windows Hello",
}
TOP_MANAGERS = {"CEO"}  # у этих должностей руководителя может не быть


def load_users() -> tuple[list[dict], bool]:
    """Пробуем с последним входом; без лицензии P1 Graph вернёт 403 — тогда без него."""
    try:
        return get_all("/users", {"$select": FIELDS + ",signInActivity"}), True
    except requests.HTTPError:
        return get_all("/users", {"$select": FIELDS}), False


def mfa_methods(user_id: str) -> list[str] | None:
    try:
        methods = get_all(f"/users/{user_id}/authentication/methods")
    except requests.HTTPError:
        return None  # нет разрешения или гостевая учётка
    return [MFA_METHODS[m["@odata.type"]] for m in methods if m.get("@odata.type") in MFA_METHODS]


def main() -> None:
    users, has_signin = load_users()
    rows, problems = [], []

    for u in users:
        name = u["displayName"]
        # Внешний аккаунт: гость ИЛИ личный аккаунт Microsoft (#EXT# в логине),
        # например создатель тенанта — у него userType Member, но он не сотрудник
        is_guest = u.get("userType") == "Guest" or "#EXT#" in u["userPrincipalName"]
        manager = get_one(f"/users/{u['id']}/manager", {"$select": "displayName"})
        groups = [g["displayName"] for g in get_all(f"/users/{u['id']}/memberOf", {"$select": "displayName"})
                  if g.get("@odata.type") == "#microsoft.graph.group"]
        mfa = mfa_methods(u["id"])

        if has_signin:
            last = (u.get("signInActivity") or {}).get("lastSignInDateTime") or "никогда"
        else:
            last = "нужен P1"

        rows.append({
            "Имя": name,
            "Логин": u["userPrincipalName"],
            "Тип": "Внешний" if is_guest else "Сотрудник",
            "Должность": u.get("jobTitle") or "",
            "Отдел": u.get("department") or "",
            "Руководитель": (manager or {}).get("displayName", ""),
            "Вход разрешён": "да" if u["accountEnabled"] else "НЕТ",
            "MFA": "н/д" if mfa is None else (", ".join(mfa) or "НЕТ"),
            "Группы": ", ".join(groups),
            "Последний вход": last,
        })

        # Проверки
        if is_guest:
            problems.append(f"{name}: внешняя учётка — проверить, нужна ли и какие у неё права")
            continue
        if not u["accountEnabled"]:
            if groups:
                problems.append(f"{name}: заблокирован, но ещё в группах: {', '.join(groups)}")
            continue
        if mfa == []:
            problems.append(f"{name}: нет MFA")
        if not u.get("department"):
            problems.append(f"{name}: не указан отдел")
        if not u.get("jobTitle"):
            problems.append(f"{name}: не указана должность")
        if not manager and u.get("jobTitle") not in TOP_MANAGERS:
            problems.append(f"{name}: нет руководителя")

    out = f"audit_{date.today():%Y-%m-%d}.csv"
    # utf-8-sig — чтобы Excel правильно открыл кириллицу и чешские буквы
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys(), delimiter=";")
        w.writeheader()
        w.writerows(rows)

    active = sum(r["Вход разрешён"] == "да" for r in rows)
    print(f"\nПользователей: {len(rows)} (активных {active}, заблокированных {len(rows) - active})")
    print(f"Отчёт: {out}")
    if not has_signin:
        print("Последний вход не показан: для signInActivity нужна лицензия Entra ID P1.")

    # Не молчим, если проверку MFA сделать не удалось — иначе отчёт выглядит чистым
    no_mfa_check = [r["Имя"] for r in rows if r["MFA"] == "н/д" and r["Тип"] == "Сотрудник"]
    if no_mfa_check:
        print(f"\n!!! MFA НЕ ПРОВЕРЕН у {len(no_mfa_check)} сотрудников — Graph отказал в доступе.")
        print("    Добавь приложению разрешение UserAuthenticationMethod.Read.All")
        print("    (тип: Разрешения приложений) и нажми «Предоставить согласие администратора».")

    print(f"\nПроблемы ({len(problems)}):" if problems else "\nПроблем не найдено.")
    for pr in problems:
        print(f"  - {pr}")


if __name__ == "__main__":
    main()
