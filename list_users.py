"""Скрипт 0: вывести всех сотрудников и все группы с участниками.

Запуск: python list_users.py
"""
from graph import get_all

USER_FIELDS = "displayName,userPrincipalName,jobTitle,department,accountEnabled"


def main() -> None:
    users = get_all("/users", {"$select": USER_FIELDS})
    print(f"\nПользователи ({len(users)}):")
    print(f"{'Имя':<22}{'Логин':<42}{'Должность':<22}{'Отдел':<14}Активен")
    for u in users:
        print(
            f"{u['displayName'] or '':<22}"
            f"{u['userPrincipalName']:<42}"
            f"{u.get('jobTitle') or '—':<22}"
            f"{u.get('department') or '—':<14}"
            f"{'да' if u['accountEnabled'] else 'НЕТ'}"
        )

    groups = get_all("/groups", {"$select": "id,displayName,groupTypes"})
    print(f"\nГруппы ({len(groups)}):")
    for g in groups:
        kind = "Microsoft 365" if "Unified" in g["groupTypes"] else "Security"
        members = get_all(f"/groups/{g['id']}/members", {"$select": "displayName"})
        names = ", ".join(m.get("displayName", "?") for m in members) or "пусто"
        print(f"  {g['displayName']:<18} [{kind}]  {names}")


if __name__ == "__main__":
    main()
