# Drukarex pilot 1.7.2rc1

Wersjonowana paczka aktualnego brancha `codex/mmu-single-nozzle-routing` do kontrolowanej instalacji na drukarkach.

Obejmuje istniejące rozszerzenia Drukarex: magazyn i przypisanie płyt, materiały eksploatacyjne, integrację kalendarza, routing pojedynczej dyszy MMU oraz skrypty Joboxa. Po poprawnie zakończonym wydruku księgowanie preferuje długość filamentu z metadanych G-code'u i loguje obok wynik odometru; przy anulowaniu lub braku poprawnych metadanych używa odometru.

To wydanie nie dodaje rezerwacji materiału ani proporcjonalnego rozliczania ręcznej zmiany szpuli podczas wydruku. Nie włącza produkcyjnego audytu w osobnej tabeli bazy — na czas pilotażu dostępne są istniejące logi źródła `metadata`/`odometer` oraz zdarzenie aktualizacji szpuli.
