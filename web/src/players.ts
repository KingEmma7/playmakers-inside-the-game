const home = [
  "Ellis",
  "Mensah",
  "Costa",
  "Reed",
  "Diallo",
  "Vega",
  "Hale",
  "Silva",
  "Okafor",
  "Marin",
  "Sato",
];
const away = [
  "Bello",
  "Novak",
  "Duarte",
  "Chen",
  "Amari",
  "Solis",
  "Luka",
  "Keita",
  "Santos",
  "Moreau",
  "Ivers",
];
export function playerName(id: string): string {
  const code = id.split("_").at(-1) || "H09";
  return (
    (code.startsWith("A") ? away : home)[Number(code.slice(1)) - 1] || "Okafor"
  );
}
