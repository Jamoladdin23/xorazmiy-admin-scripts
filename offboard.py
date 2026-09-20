"""Скрипт 2: офбординг уволенного сотрудника.

Порядок важен — сначала отрезаем доступ, потом прибираемся:
  1. блокирует вход
  2. отзывает все активные сессии (выкидывает со всех устройств)
  3. снимает лицензии (если есть)
  4. удаляет из всех групп
  5. предупреждает о том, что нужно решить человеку:
     подчинённые без руководителя, группы, где он владелец
  6. сохраняет журнал в offboard_logs/ — из него видно, что было, и можно откатить

Пользователь НЕ удаляется: в компании учётку обычно держат заблокированной
30+ дней, пока руководитель забирает файлы и почту.

Примеры:
  python offboard.py temur.zar --dry-run
  python offboard.py temur.zar
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

from graph import delete, get_all, get_one, patch, post

DOMAIN = os.environ.get("DOMAIN", "xorazmiy.tech")
GROUP_TYPE = "#microsoft.graph.group"


def main() -> None:
    p = argparse.ArgumentParser(description="Офбординг сотрудника в Entra ID")
    p.add_argument("login", help="логин без домена, напр. temur.zar")
    p.add_argument("--dry-run", action="store_true", help="только показать, ничего не менять")
    p.add_argument("--yes", action="store_true", help="не спрашивать подтверждение")
    a = p.parse_args()

    upn = a.login if "@" in a.login else f"{a.login}@{DOMAIN}"
    user = get_one(
        f"/users/{upn}",
        {"$select": "id,displayName,userPrincipalName,accountEnabled,assignedLicenses,jobTitle,department"},
    )
    if not user:
        sys.exit(f"Пользователь не найден: {upn}")

    # Всё, что нужно знать ДО изменений
    member_of = [o for o in get_all(f"/users/{user['id']}/memberOf", {"$select": "id,displayName"})
                 if o.get("@odata.type") == GROUP_TYPE]
    owned = [o for o in get_all(f"/users/{user['id']}/ownedObjects", {"$select": "id,displayName"})
             if o.get("@odata.type") == GROUP_TYPE]
    reports = get_all(f"/users/{user['id']}/directReports", {"$select": "displayName"})
    licenses = [l["skuId"] for l in user.get("assignedLicenses", [])]

    print(f"\nСотрудник:   {user['displayName']} <{user['userPrincipalName']}>")
    print(f"Должность:   {user.get('jobTitle') or '—'}, отдел {user.get('department') or '—'}")
    print(f"Вход:        {'разрешён' if user['accountEnabled'] else 'уже заблокирован'}")
    print(f"Группы:      {', '.join(g['displayName'] for g in member_of) or '—'}")
    print(f"Лицензии:    {len(licenses) or 'нет'}")
    if owned:
        print(f"ВНИМАНИЕ владелец групп: {', '.join(g['displayName'] for g in owned)}")
    if reports:
        print(f"ВНИМАНИЕ подчинённые:    {', '.join(r.get('displayName', '?') for r in reports)}")

    if a.dry_run:
        print("\n--dry-run: ничего не изменено.")
        return

    if not a.yes:
        typed = input(f"\nЭто заблокирует {upn}. Введи логин для подтверждения: ").strip()
        if typed not in (a.login, upn):
            sys.exit("Не совпало — отменено, ничего не изменено.")

    print()
    # 1. Блокировка входа
    patch(f"/users/{user['id']}", {"accountEnabled": False})
    print("+ вход заблокирован")

    # 2. Отзыв сессий: токены на телефоне/ноутбуке перестают работать
    post(f"/users/{user['id']}/revokeSignInSessions", {})
    print("+ все сессии отозваны")

    # 3. Лицензии
    if licenses:
        post(f"/users/{user['id']}/assignLicense", {"addLicenses": [], "removeLicenses": licenses})
        print(f"+ снято лицензий: {len(licenses)}")

    # 4. Группы
    removed, failed = [], []
    for g in member_of:
        try:
            delete(f"/groups/{g['id']}/members/{user['id']}/$ref")
            removed.append(g["displayName"])
            print(f"+ удалён из {g['displayName']}")
        except RuntimeError as e:
            failed.append(g["displayName"])
            print(f"! не удалось удалить из {g['displayName']}: {e}")

    # 5. Журнал
    os.makedirs("offboard_logs", exist_ok=True)
    stamp = datetime.now(timezone.utc)
    log = {
        "user": user["userPrincipalName"],
        "displayName": user["displayName"],
        "offboarded_at": stamp.isoformat(),
        "removed_from_groups": removed,
        "failed_groups": failed,
        "removed_license_skus": licenses,
        "still_owner_of": [g["displayName"] for g in owned],
        "direct_reports": [r.get("displayName") for r in reports],
    }
    path = f"offboard_logs/{a.login.split('@')[0]}_{stamp:%Y-%m-%d}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    print(f"\nЖурнал: {path}")

    if owned or reports:
        print("\nОсталось решить вручную:")
        if owned:
            print(f"  - назначить нового владельца: {', '.join(g['displayName'] for g in owned)}")
        if reports:
            print(f"  - новый руководитель для: {', '.join(r.get('displayName', '?') for r in reports)}")


if __name__ == "__main__":
    main()
