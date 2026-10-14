#!/usr/bin/env bash
set -euo pipefail

lab_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
backup="$lab_dir/backup.sh"
temp_dir="$(mktemp -d)"
trap 'rm -rf -- "$temp_dir"' EXIT

source_dir="$temp_dir/test source"
dest_dir="$temp_dir/backups"
dry_dir="$temp_dir/dry-run"
mkdir -p "$source_dir" "$dest_dir" "$dry_dir"
printf 'Test file\n' > "$source_dir/file.txt"

# 1. Створюється один справжній архів із файлом джерела.
bash "$backup" --source "$source_dir" --dest "$dest_dir" --keep 5
archives=("$dest_dir"/*.tar.gz)
[[ ${#archives[@]} -eq 1 && -f "${archives[0]}" ]]
tar -tzf "${archives[0]}" | grep -Fx 'test source/file.txt'
echo "PASS: archive created"

# 2. Dry-run не створює архів.
bash "$backup" --source "$source_dir" --dest "$dry_dir" --dry-run
[[ -z "$(find "$dry_dir" -type f -name '*.tar.gz' -print)" ]]
echo "PASS: dry-run creates no archive"

# 3. Неіснуюче джерело повертає ненульовий код.
if bash "$backup" --source "$temp_dir/missing" --dest "$dest_dir"; then
    echo "FAIL: invalid source was accepted" >&2
    exit 1
fi
echo "PASS: invalid source rejected"

# 4. Після трьох запусків із --keep 2 залишаються два архіви.
for run in 1 2 3; do
    echo "Backup run: $run"
    bash "$backup" --source "$source_dir" --dest "$dest_dir" --keep 2
done
archives=("$dest_dir"/*.tar.gz)
[[ ${#archives[@]} -eq 2 ]]
for archive in "${archives[@]}"; do
    tar -tzf "$archive" > /dev/null
done
echo "PASS: keep retains two archives"

echo "All backup tests passed"
