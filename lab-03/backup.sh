#!/usr/bin/env bash
set -euo pipefail

source_dir=""
dest_dir=""
keep=5
dry_run=false

help() {
    echo "Usage: ./backup.sh --source <path> --dest <path> [--keep N] [--dry-run]"
}

fail() {
    echo "ERROR: $2" >&2
    exit "$1"
}

# читаємо аргументи
while [[ $# -gt 0 ]]; do
    case "$1" in
        --source)
            [[ $# -ge 2 ]] || fail 1 "Немає значення для --source"
            source_dir="$2"
            shift 2
            ;;

        --dest)
            [[ $# -ge 2 ]] || fail 1 "Немає значення для --dest"
            dest_dir="$2"
            shift 2
            ;;

        --keep)
            [[ $# -ge 2 ]] || fail 1 "Немає значення для --keep"
            keep="$2"
            shift 2
            ;;

        --dry-run)
            dry_run=true
            shift
            ;;

        --help)
            help
            exit 0
            ;;

        *)
            fail 1 "Невідомий параметр: $1"
            ;;
    esac
done

# перевірки
[[ -n "$source_dir" ]] || fail 1 "Потрібно вказати --source"
[[ -n "$dest_dir" ]] || fail 1 "Потрібно вказати --dest"

[[ -d "$source_dir" ]] || fail 2 "Source не існує"
[[ -r "$source_dir" ]] || fail 3 "Source не читається"

[[ "$keep" =~ ^[1-9][0-9]*$ ]] || fail 1 "--keep має бути додатним числом"

# створюємо destination
if [[ ! -d "$dest_dir" ]]; then
    if "$dry_run"; then
        echo "[DRY-RUN] mkdir -p \"$dest_dir\""
    else
        mkdir -p "$dest_dir" || fail 4 "Не вдалося створити destination"
    fi
fi

source_name="$(basename "$source_dir")"
source_parent="$(dirname "$source_dir")"

timestamp="$(date +%Y-%m-%d-%H%M%S)"
archive="$dest_dir/$source_name-$timestamp.tar.gz"

# щоб не перезаписати архів з тим самим ім'ям
while [[ -e "$archive" ]]; do
    sleep 1
    timestamp="$(date +%Y-%m-%d-%H%M%S)"
    archive="$dest_dir/$source_name-$timestamp.tar.gz"
done

files_count="$(find "$source_dir" -type f | wc -l)"

# створення архіву
if "$dry_run"; then
    echo "[DRY-RUN] tar -czf \"$archive\" -C \"$source_parent\" \"$source_name\""
else
    tar -czf "$archive" -C "$source_parent" "$source_name" \
        || fail 5 "Не вдалося створити архів"

    echo "Створено: $archive"
fi

# список архівів цього source
mapfile -t archives < <(
    find "$dest_dir" \
        -maxdepth 1 \
        -type f \
        -name "$source_name-????-??-??-??????.tar.gz" \
        -print | sort
)

# для dry-run додаємо майбутній архів у список
if "$dry_run"; then
    archives+=("$archive")
    mapfile -t archives < <(printf '%s\n' "${archives[@]}" | sort)
fi

removed=0
count="${#archives[@]}"

# видаляємо зайві старі архіви
if (( count > keep )); then
    to_remove=$((count - keep))

    for ((i = 0; i < to_remove; i++)); do
        if "$dry_run"; then
            echo "[DRY-RUN] rm \"${archives[$i]}\""
        else
            rm "${archives[$i]}" \
                || fail 6 "Не вдалося видалити старий архів"

            echo "Видалено: ${archives[$i]}"
        fi

        removed=$((removed + 1))
    done
fi

# лог
if "$dry_run"; then
    echo "[DRY-RUN] log:"
    echo "$(date -Iseconds) | source=$source_dir | files=$files_count | removed=$removed"
else
    archive_size="$(stat -c %s "$archive")"

    echo "$(date -Iseconds) | source=$source_dir | result=SUCCESS | files=$files_count | removed=$removed | size=$archive_size" \
        >> "$dest_dir/backup.log" \
        || fail 7 "Не вдалося записати лог"
fi
