export default function Brand({ large = false }: { large?: boolean }) {
  const size = large ? 44 : 34;

  return (
    <span className={`inline-flex shrink-0 items-center gap-2.5 text-fg ${large ? "text-[1.85rem]" : "text-[1.38rem]"}`}>
      <img
        src={`${import.meta.env.BASE_URL}selfx-mark.svg`}
        alt=""
        width={size}
        height={size}
        className="shrink-0"
      />
      <span className="font-bold leading-none tracking-[-0.065em]">Self<span className="text-primary">X</span></span>
    </span>
  );
}
