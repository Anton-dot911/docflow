export type Theme = "light" | "dark";

interface ThemeSwitchProps {
  theme: Theme;
  onChange: (theme: Theme) => void;
}

const OPTIONS: { value: Theme; label: string; swatch: string }[] = [
  { value: "light", label: "Світла", swatch: "#ffffff" },
  { value: "dark", label: "Темна", swatch: "#0b1020" },
];

// Hidden radio inputs + label pills: a real radiogroup (keyboard/AT operable)
// whose `:checked` state also drives the CSS `:has()` fallback in review.css,
// so the theme still switches if JS fails to load (UI_SPEC §4).
export function ThemeSwitch({ theme, onChange }: ThemeSwitchProps) {
  return (
    <div>
      {OPTIONS.map((option) => (
        <input
          key={option.value}
          type="radio"
          className="rv-theme-radio"
          name="rv-theme"
          id={`rv-theme-${option.value}`}
          checked={theme === option.value}
          onChange={() => onChange(option.value)}
        />
      ))}
      <div className="rv-themes" role="radiogroup" aria-label="Перемикач теми">
        {OPTIONS.map((option) => (
          <label
            key={option.value}
            className="rv-theme-pill"
            htmlFor={`rv-theme-${option.value}`}
            role="radio"
            aria-checked={theme === option.value}
          >
            <span
              className="rv-theme-swatch"
              style={{ background: option.swatch }}
              aria-hidden="true"
            />
            {option.label}
          </label>
        ))}
      </div>
    </div>
  );
}
