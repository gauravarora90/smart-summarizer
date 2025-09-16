package main

import (
	"log"
	"net/http"

	"github.com/gauravarora90/smart-summarizer/go-api/handlers"
	"github.com/gorilla/mux"
)

func main() {
    r := mux.NewRouter()
    r.HandleFunc("/health", handlers.Health).Methods("GET")
    r.HandleFunc("/summarize", handlers.SummarizeHandler).Methods("POST")
    log.Println("Go API listening at :8080")
    http.ListenAndServe(":8080", r)
}
